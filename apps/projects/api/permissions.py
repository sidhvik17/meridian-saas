"""Object- and tenant-level API permissions (IDOR defenses).

Layering:

1. ``IsAuthenticated`` (DRF default) — identity.
2. ``IsTenantMember`` — the authenticated user holds an *active* membership
   in the tenant resolved from the subdomain. Authentication alone never
   grants tenant access.
3. ``RoleBasedWritePermission`` — write methods require an editor role;
   destructive methods require admin/owner.
4. Object-level: the object's ``tenant_id`` must equal the resolved tenant
   (belt-and-braces on top of the fail-closed manager).
"""
from __future__ import annotations

from typing import Final

from django.db import models
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.tenants.models import Membership

_EDITOR_ROLES: Final[frozenset[str]] = frozenset(
    {Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.MEMBER}
)
_ADMIN_ROLES: Final[frozenset[str]] = frozenset(
    {Membership.Role.OWNER, Membership.Role.ADMIN}
)


def get_membership(request: Request) -> Membership | None:
    """Return (and per-request cache) the caller's active membership in the
    resolved tenant."""
    cached = getattr(request, "_tenant_membership", None)
    if cached is not None:
        return cached
    tenant = getattr(request, "tenant", None)
    if tenant is None or not request.user.is_authenticated:
        return None
    membership = Membership.objects.filter(
        user=request.user, tenant=tenant, is_active=True
    ).first()
    request._tenant_membership = membership  # type: ignore[attr-defined]
    return membership


class IsTenantMember(BasePermission):
    """Allow only users holding an active membership in the request tenant."""

    message = "You are not a member of this organisation."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return get_membership(request) is not None

    def has_object_permission(
        self, request: Request, view: APIView, obj: models.Model
    ) -> bool:
        tenant = getattr(request, "tenant", None)
        obj_tenant_id = getattr(obj, "tenant_id", None)
        # Explicit object-tenant comparison: even if a queryset bug ever
        # surfaced a foreign object, the comparison here stops the response.
        return tenant is not None and obj_tenant_id == tenant.pk


class RoleBasedWritePermission(BasePermission):
    """Reads for any member; writes for editors; deletes for admins."""

    message = "Your role does not permit this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        membership = get_membership(request)
        if membership is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        if request.method == "DELETE":
            return membership.role in _ADMIN_ROLES
        return membership.role in _EDITOR_ROLES
