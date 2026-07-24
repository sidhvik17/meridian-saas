"""Tenant-scoped API viewsets."""
from __future__ import annotations

from django.db.models import QuerySet
from rest_framework import permissions, serializers, viewsets

from apps.projects.api.permissions import IsTenantMember, RoleBasedWritePermission
from apps.projects.api.serializers import ProjectSerializer, WorkItemSerializer
from apps.projects.models import Project, WorkItem


class TenantScopedViewSetMixin:
    """Shared permission stack for tenant-scoped endpoints.

    Note that ``get_queryset`` in subclasses relies on the fail-closed
    default manager — there is no code path that returns an unscoped
    queryset to the API layer.
    """

    permission_classes = [
        permissions.IsAuthenticated,
        IsTenantMember,
        RoleBasedWritePermission,
    ]


class ProjectViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    serializer_class = ProjectSerializer

    def get_queryset(self) -> QuerySet[Project]:
        # Project.objects is tenant-scoped (fail-closed manager).
        return Project.objects.select_related("owner").order_by("-created_at")

    def perform_create(self, serializer: serializers.BaseSerializer[Project]) -> None:
        # Owner is always the caller; tenant is injected by
        # TenantOwnedModel.save() from the request-bound context. Neither is
        # client-controllable.
        serializer.save(owner=self.request.user)


class WorkItemViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    serializer_class = WorkItemSerializer

    def get_queryset(self) -> QuerySet[WorkItem]:
        queryset = WorkItem.objects.select_related("project", "assignee")
        project_id = self.request.query_params.get("project")
        if project_id is not None and project_id.isdigit():
            queryset = queryset.filter(project_id=int(project_id))
        return queryset.order_by("-created_at")
