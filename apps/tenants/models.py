"""Tenancy domain: Tenant, Domain, Membership."""
from __future__ import annotations

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import TimeStampedModel

_hostname_validator = RegexValidator(
    regex=r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$",
    message="Enter a valid lowercase hostname.",
)

_slug_validator = RegexValidator(
    regex=r"^[a-z][a-z0-9-]{1,61}[a-z0-9]$",
    message="Slug must be lowercase alphanumeric/hyphen, 3-63 chars.",
)


class Tenant(TimeStampedModel):
    """A customer organisation. Not itself tenant-scoped."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=63, unique=True, validators=[_slug_validator])
    is_active = models.BooleanField(default=True, db_index=True)

    def __str__(self) -> str:
        return self.slug


class Domain(TimeStampedModel):
    """A hostname mapped to a tenant (``acme.meridian.app`` → Acme).

    Hostnames are stored lowercase and validated; the resolution middleware
    only ever does an exact-match lookup, so lookalike or wildcard tricks in
    the Host header cannot match a different tenant.
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="domains")
    hostname = models.CharField(
        max_length=253, unique=True, validators=[_hostname_validator]
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant"],
                condition=models.Q(is_primary=True),
                name="tenants_domain_one_primary_per_tenant",
            ),
        ]

    def __str__(self) -> str:
        return self.hostname

    def save(self, *args: object, **kwargs: object) -> None:
        self.hostname = self.hostname.strip().lower()
        super().save(*args, **kwargs)


class Membership(TimeStampedModel):
    """Role-bearing link between a user and a tenant.

    Authorisation source of truth for the API layer: a user with no active
    membership in the resolved tenant is rejected regardless of
    authentication state.
    """

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"
        VIEWER = "viewer", "Viewer"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "tenant"], name="tenants_membership_unique_user_tenant"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.tenant_id}:{self.role}"
