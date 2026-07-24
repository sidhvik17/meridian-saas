"""API serializers.

Fields are always enumerated explicitly — ``fields = "__all__"`` is banned
because it silently exposes new columns (mass-assignment / data-exposure
risk) the moment a model grows one.
"""
from __future__ import annotations

from typing import Any, ClassVar

from rest_framework import serializers

from apps.projects.models import Project, WorkItem
from apps.tenants.models import Membership


class ProjectSerializer(serializers.ModelSerializer):
    owner_email = serializers.EmailField(source="owner.email", read_only=True)

    class Meta:
        model = Project
        fields: ClassVar[list[str]] = [
            "id",
            "name",
            "key",
            "description",
            "owner_email",
            "is_archived",
            "created_at",
            "updated_at",
        ]
        read_only_fields: ClassVar[list[str]] = ["id", "created_at", "updated_at"]


class WorkItemSerializer(serializers.ModelSerializer):
    # PrimaryKeyRelatedField querysets are tenant-scoped at access time via
    # the fail-closed manager, so a client cannot attach a work item to
    # another tenant's project by guessing its id (IDOR-by-reference).
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects)

    class Meta:
        model = WorkItem
        fields: ClassVar[list[str]] = [
            "id",
            "project",
            "title",
            "status",
            "assignee",
            "due_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields: ClassVar[list[str]] = ["id", "created_at", "updated_at"]

    def validate_assignee(self, value: Any) -> Any:
        """Assignee must be an active member of the current tenant."""
        if value is None:
            return value
        request = self.context["request"]
        tenant = getattr(request, "tenant", None)
        is_member = (
            tenant is not None
            and Membership.objects.filter(
                user=value, tenant=tenant, is_active=True
            ).exists()
        )
        if not is_member:
            raise serializers.ValidationError(
                "Assignee must be a member of this organisation."
            )
        return value
