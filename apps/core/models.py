"""Shared abstract models.

``TenantOwnedModel`` is the cornerstone of tenant isolation: every model that
stores customer data inherits from it and is therefore scoped by the
fail-closed ``TenantAwareManager`` by default.
"""
from __future__ import annotations

from typing import Any, ClassVar

from django.db import models

from apps.tenants.context import TenantContextError, get_current_tenant_id
from apps.tenants.managers import TenantAwareManager


class TimeStampedModel(models.Model):
    """Abstract base adding creation/modification timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantOwnedModel(TimeStampedModel):
    """Abstract base for every model that stores tenant data.

    Isolation properties:

    - ``objects`` (the *default* manager) hard-scopes every queryset to the
      tenant bound in the current execution context and raises
      ``TenantContextError`` when none is bound (fail-closed).
    - ``unscoped`` exists for framework internals and audited system code
      only; application code must never reach for it directly.
    - ``save()`` auto-assigns the bound tenant so application code cannot
      accidentally create a row for the wrong tenant.
    """

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        editable=False,
        related_name="+",
    )

    objects: ClassVar[TenantAwareManager[Any]] = TenantAwareManager()
    unscoped: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        abstract = True
        # Django internals (related descriptors, deletion collector) must use
        # the unscoped manager; request-path code keeps the scoped default.
        base_manager_name = "unscoped"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.tenant_id is None:
            tenant_id = get_current_tenant_id()
            if tenant_id is None:
                raise TenantContextError(
                    f"Cannot save {type(self).__name__} without a bound tenant. "
                    "Bind one with tenant_context() or assign .tenant explicitly."
                )
            self.tenant_id = tenant_id
        super().save(*args, **kwargs)
