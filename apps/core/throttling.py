"""API throttling — three independent layers, all Redis-backed.

- ``burst``     : short-window per-user limit (absorbs scripting mistakes).
- ``sustained`` : daily per-user limit.
- ``tenant``    : daily per-tenant limit (one noisy tenant cannot starve the
  platform; also blunts credential-stuffing amplification).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle

if TYPE_CHECKING:
    # Type-hint-only imports. Importing rest_framework.views at module level
    # is a circular import: DRF's APIView class body resolves
    # DEFAULT_THROTTLE_CLASSES, which imports this module.
    from rest_framework.request import Request
    from rest_framework.views import APIView


class BurstRateThrottle(UserRateThrottle):
    scope = "burst"


class SustainedRateThrottle(UserRateThrottle):
    scope = "sustained"


class TenantRateThrottle(SimpleRateThrottle):
    """Throttle keyed on the resolved tenant rather than the user."""

    scope = "tenant"

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return None  # Public hosts: tenant throttle does not apply.
        return self.cache_format % {"scope": self.scope, "ident": str(tenant.pk)}
