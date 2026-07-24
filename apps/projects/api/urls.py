from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.projects.api.views import ProjectViewSet, WorkItemViewSet

router = DefaultRouter()
router.register("projects", ProjectViewSet, basename="project")
router.register("work-items", WorkItemViewSet, basename="workitem")

urlpatterns = router.urls
