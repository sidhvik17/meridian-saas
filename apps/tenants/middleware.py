"""Tenant resolution from the request host.

Security properties:

- ``request.get_host()`` validates against ``ALLOWED_HOSTS`` *before* this
  middleware runs, so a forged ``Host`` header raises ``DisallowedHost``
  upstream and never reaches tenant resolution.
- Hostnames are matched exactly against the ``Domain`` table (stored
  lowercase, validated) — no pattern matching, no implicit fallbacks.
- Unknown hosts get a plain 404; the response does not reveal whether a
  tenant exists (anti-enumeration). Negative lookups are cached to blunt
  enumeration-driven database load.
- The ContextVar binding is always reset in ``finally`` so worker reuse can
  never leak one tenant's scope into the next request.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound

from apps.tenants.context import bind_tenant, unbind_tenant
from apps.tenants.models import Domain, Tenant

logger = logging.getLogger(__name__)

_DOMAIN_CACHE_TTL: Final[int] = 300  # seconds
_NEGATIVE_SENTINEL: Final[int] = 0  # cached "no such domain" marker

# Paths reachable on any host without tenant resolution (load-balancer
# health checks may arrive with bare-IP Host headers).
_EXEMPT_PATHS: Final[frozenset[str]] = frozenset({"/healthz/"})


class TenantResolutionMiddleware:
    """Bind the tenant matching the request host to the execution context."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path in _EXEMPT_PATHS:
            request.tenant = None  # type: ignore[attr-defined]
            return self.get_response(request)

        host = request.get_host().split(":", 1)[0].lower()

        if host in settings.PUBLIC_HOSTS:
            # Marketing site / admin / auth pages: no tenant context.
            request.tenant = None  # type: ignore[attr-defined]
            return self.get_response(request)

        tenant = self._resolve_tenant(host)
        if tenant is None:
            return HttpResponseNotFound("Not found.")

        request.tenant = tenant  # type: ignore[attr-defined]
        token = bind_tenant(tenant.pk)
        try:
            return self.get_response(request)
        finally:
            unbind_tenant(token)

    @staticmethod
    def _resolve_tenant(host: str) -> Tenant | None:
        """Resolve a hostname to an active tenant, with positive and
        negative Redis caching."""
        cache_key = f"tenant:domain:{host}"
        cached: int | None = cache.get(cache_key)

        if cached == _NEGATIVE_SENTINEL:
            return None
        if cached is not None:
            tenant = Tenant.objects.filter(pk=cached, is_active=True).first()
            if tenant is not None:
                return tenant
            cache.delete(cache_key)  # stale: tenant deactivated since cached

        domain = (
            Domain.objects.select_related("tenant")
            .filter(hostname=host, tenant__is_active=True)
            .first()
        )
        if domain is None:
            cache.set(cache_key, _NEGATIVE_SENTINEL, _DOMAIN_CACHE_TTL)
            logger.info("Tenant resolution miss for host %s", host)
            return None

        cache.set(cache_key, domain.tenant_id, _DOMAIN_CACHE_TTL)
        return domain.tenant
