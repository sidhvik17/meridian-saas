"""Fail-closed tenant-scoped manager.

This is the single most important security control in the codebase: it makes
cross-tenant data access an *exception to be raised*, not a bug to be found.
"""
from __future__ import annotations

from typing import TypeVar

from django.db import models

from apps.tenants.context import TenantContextError, get_current_tenant_id

_ModelT = TypeVar("_ModelT", bound=models.Model)


class TenantAwareManager(models.Manager[_ModelT]):
    """Default manager that hard-scopes every queryset to the bound tenant.

    Fail-closed semantics: if no tenant is bound to the current execution
    context, the manager raises ``TenantContextError`` instead of silently
    returning rows across tenants. System code (Celery tasks, management
    commands, data migrations) must opt in explicitly via
    :meth:`for_tenant` or ``tenant_context()``.
    """

    def get_queryset(self) -> models.QuerySet[_ModelT]:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise TenantContextError(
                f"{self.model.__name__} was queried without a bound tenant. "
                "Bind one with tenant_context(tenant_id) or use "
                f"{self.model.__name__}.objects.for_tenant(tenant_id) for "
                "audited system access."
            )
        return super().get_queryset().filter(tenant_id=tenant_id)

    def for_tenant(self, tenant_id: int) -> models.QuerySet[_ModelT]:
        """Explicit, greppable escape hatch for system code.

        Bypasses the ContextVar and scopes directly to ``tenant_id``. Every
        call site is auditable with ``grep -rn "for_tenant("``.
        """
        return super().get_queryset().filter(tenant_id=tenant_id)
