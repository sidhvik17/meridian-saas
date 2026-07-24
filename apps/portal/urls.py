from __future__ import annotations

from django.urls import path

from apps.portal import views

app_name = "portal"

urlpatterns = [
    path("", views.home, name="landing"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("projects/", views.project_list, name="projects"),
    path("projects/<int:pk>/", views.project_detail, name="project-detail"),
    path("work-items/<int:pk>/status/", views.work_item_set_status, name="workitem-status"),
    path("billing/", views.billing, name="billing"),
    path("billing/invoices/<int:pk>/pay/", views.invoice_mark_paid, name="invoice-pay"),
    path("members/", views.member_list, name="members"),
]
