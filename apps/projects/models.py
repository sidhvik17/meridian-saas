"""Work-management domain models. All tenant-owned."""
from __future__ import annotations

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import TenantOwnedModel

_project_key_validator = RegexValidator(
    regex=r"^[A-Z][A-Z0-9]{1,9}$",
    message="Project key must be 2-10 uppercase alphanumerics starting with a letter.",
)


class Project(TenantOwnedModel):
    """A unit of work organisation within a tenant."""

    name = models.CharField(max_length=255)
    key = models.CharField(max_length=10, validators=[_project_key_validator])
    description = models.TextField(blank=True, max_length=10_000)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_projects",
    )
    is_archived = models.BooleanField(default=False, db_index=True)

    class Meta(TenantOwnedModel.Meta):
        abstract = False
        constraints = [
            # Key is unique within a tenant, not globally — tenants must not
            # be able to detect each other's keys via uniqueness errors.
            models.UniqueConstraint(
                fields=["tenant", "key"], name="projects_project_unique_key_per_tenant"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.key}: {self.name}"


class WorkItem(TenantOwnedModel):
    """A trackable item (task/bug/story) inside a project."""

    class Status(models.TextChoices):
        BACKLOG = "backlog", "Backlog"
        IN_PROGRESS = "in_progress", "In progress"
        IN_REVIEW = "in_review", "In review"
        DONE = "done", "Done"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="items")
    title = models.CharField(max_length=500)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.BACKLOG, db_index=True
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_items",
    )
    due_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantOwnedModel.Meta):
        abstract = False
        indexes = [
            models.Index(fields=["tenant", "project", "status"]),
        ]

    def __str__(self) -> str:
        return self.title
