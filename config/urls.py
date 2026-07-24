"""Root URL configuration."""
from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.core.views import health_check

urlpatterns = [
    # Admin path is environment-configurable (see SECURITY_AUDIT.md V-10);
    # it is served only on public (non-tenant) hosts.
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/", include(("apps.projects.api.urls", "projects"), namespace="api-v1")),
    path("healthz/", health_check, name="health-check"),
    # Session auth (login/logout only; password reset needs an email backend).
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Server-rendered portal UI.
    path("", include("apps.portal.urls")),
]
