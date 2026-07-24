"""Celery tasks for billing.

Conventions:

- JSON-serialisable arguments only (Decimal travels as string).
- Every task receives an explicit ``tenant_id`` and binds it itself; no task
  relies on ambient state from the enqueueing request.
- ``acks_late`` + idempotent bodies make redelivery after a worker crash safe.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from celery import shared_task

from apps.billing.services import InvoiceLine, issue_invoice
from apps.billing.webhooks import WebhookDeliveryError, deliver

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    autoretry_for=(Exception,),
    acks_late=True,
)
def issue_invoice_task(
    self: Any,
    *,
    tenant_id: int,
    subscription_id: int,
    lines: list[dict[str, str]],
    idempotency_key: str,
) -> int:
    """Issue an invoice asynchronously. Idempotent via ``idempotency_key``."""
    parsed_lines = [
        InvoiceLine(description=line["description"], amount=Decimal(line["amount"]))
        for line in lines
    ]
    invoice = issue_invoice(
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        lines=parsed_lines,
        idempotency_key=uuid.UUID(idempotency_key),
    )
    logger.info(
        "Issued invoice id=%s for tenant=%s subscription=%s",
        invoice.pk,
        tenant_id,
        subscription_id,
    )
    return invoice.pk


@shared_task(
    bind=True,
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=3600,
    autoretry_for=(WebhookDeliveryError, Exception),
    acks_late=True,
)
def send_invoice_paid_webhook(self: Any, *, tenant_id: int, invoice_id: int) -> None:
    """Deliver an HMAC-signed 'invoice.paid' event to the tenant's endpoint.

    Endpoint URL and signing secret come from the tenant's (out-of-scope
    here) integration settings; the payload carries identifiers only — no
    PII, no amounts beyond what the receiver already owns.
    """
    from apps.billing.models import Invoice
    from apps.tenants.context import tenant_context

    with tenant_context(tenant_id):
        invoice = Invoice.objects.filter(pk=invoice_id).first()
        if invoice is None or invoice.status != Invoice.Status.PAID:
            logger.warning(
                "Skipping webhook: invoice id=%s not found or not paid", invoice_id
            )
            return

        config = _get_tenant_webhook_config(tenant_id)
        if config is None:
            return  # Tenant has not configured webhooks.

        url, secret = config
        event = {
            "type": "invoice.paid",
            "invoice_id": invoice.pk,
            "invoice_number": invoice.number,
            "tenant_id": tenant_id,
        }
        status = deliver(url, event, secret=secret)
        logger.info("Webhook invoice.paid delivered (%s) for invoice=%s", status, invoice_id)


def _get_tenant_webhook_config(tenant_id: int) -> tuple[str, bytes] | None:
    """Fetch the tenant's webhook URL and per-tenant signing secret.

    Secrets live in the platform secret store keyed by tenant, *not* in the
    application database alongside the data they protect.
    """
    # Integration point — intentionally a stub in this reference codebase.
    return None
