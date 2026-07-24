"""Outbound webhook delivery with SSRF guards and HMAC signing."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
from typing import Any
from urllib.parse import urlsplit

import httpx

_DELIVERY_TIMEOUT_SECONDS = 10.0


class WebhookDeliveryError(RuntimeError):
    """Raised when a webhook cannot be delivered safely."""


def validate_webhook_url(url: str) -> None:
    """Reject URLs that could be used to pivot into internal networks (SSRF).

    Rules: https only, no userinfo, no IP-literal hosts (public DNS names
    only), no non-standard ports. DNS-rebinding remains a residual risk;
    see SECURITY_AUDIT.md V-08 for the egress-proxy compensating control.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise WebhookDeliveryError("Webhook URLs must use https.")
    if parts.username or parts.password:
        raise WebhookDeliveryError("Webhook URLs must not contain credentials.")
    if parts.port not in (None, 443):
        raise WebhookDeliveryError("Webhook URLs must use port 443.")
    hostname = parts.hostname or ""
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass  # A DNS name — acceptable.
    else:
        raise WebhookDeliveryError("Webhook URLs must not use IP-literal hosts.")
    if hostname in ("localhost",) or hostname.endswith((".local", ".internal")):
        raise WebhookDeliveryError("Webhook URLs must resolve to public hosts.")


def sign_payload(payload: bytes, *, secret: bytes) -> str:
    """Return the hex HMAC-SHA256 signature for a payload."""
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def deliver(url: str, event: dict[str, Any], *, secret: bytes) -> int:
    """POST a signed JSON event to a tenant-configured webhook endpoint.

    The receiver verifies ``X-Meridian-Signature`` with its shared secret
    (constant-time comparison on their side; we only ever *generate* here).
    """
    validate_webhook_url(url)
    body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
    signature = sign_payload(body, secret=secret)
    response = httpx.post(
        url,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Meridian-Signature": f"sha256={signature}",
        },
        timeout=_DELIVERY_TIMEOUT_SECONDS,
        follow_redirects=False,  # Redirects could bounce the request to an internal host.
    )
    response.raise_for_status()
    return response.status_code
