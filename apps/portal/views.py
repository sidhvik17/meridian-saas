"""Server-rendered portal views.

Same security model as the API: every tenant page requires an active
membership in the tenant resolved from the subdomain; writes require an
editor role; the fail-closed managers scope all queries underneath.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from functools import wraps
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import User
from apps.billing.models import Invoice, Subscription
from apps.billing.services import InvoiceLine, issue_invoice, mark_invoice_paid
from apps.portal.forms import AddMemberForm, InvoiceLineForm, ProjectForm, WorkItemForm
from apps.projects.models import Project, WorkItem
from apps.tenants.models import Membership

_EDITOR_ROLES = (Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.MEMBER)
_ADMIN_ROLES = (Membership.Role.OWNER, Membership.Role.ADMIN)

ViewFunc = Callable[..., HttpResponse]


def tenant_member_required(roles: tuple[str, ...] | None = None) -> Callable[[ViewFunc], ViewFunc]:
    """Require an active membership in the resolved tenant (and optionally a
    role from ``roles``). Mirrors the API permission stack for HTML pages."""

    def decorator(view: ViewFunc) -> ViewFunc:
        @wraps(view)
        @login_required
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            tenant = getattr(request, "tenant", None)
            if tenant is None:
                return redirect("portal:landing")
            membership = (
                Membership.objects.filter(user=request.user, tenant=tenant, is_active=True)
                .select_related("tenant")
                .first()
            )
            if membership is None:
                return HttpResponseForbidden("You are not a member of this organisation.")
            if roles is not None and membership.role not in roles:
                messages.error(request, "Your role does not permit that action.")
                return redirect("portal:dashboard")
            request.membership = membership  # type: ignore[attr-defined]
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def home(request: HttpRequest) -> HttpResponse:
    """Public host → landing page. Tenant host → dashboard (or login)."""
    if getattr(request, "tenant", None) is None:
        return render(request, "portal/landing.html")
    if request.user.is_authenticated:
        return redirect("portal:dashboard")
    return redirect("login")


@tenant_member_required()
def dashboard(request: HttpRequest) -> HttpResponse:
    subscription = Subscription.objects.filter(
        status__in=(Subscription.Status.TRIALING, Subscription.Status.ACTIVE)
    ).first()
    latest_invoice = Invoice.objects.order_by("-created_at").first()
    context = {
        "project_count": Project.objects.count(),
        "open_item_count": WorkItem.objects.exclude(status=WorkItem.Status.DONE).count(),
        "member_count": Membership.objects.filter(
            tenant=request.tenant, is_active=True
        ).count(),
        "recent_items": WorkItem.objects.select_related("project", "assignee").order_by(
            "-updated_at"
        )[:8],
        "subscription": subscription,
        "latest_invoice": latest_invoice,
    }
    return render(request, "portal/dashboard.html", context)


@tenant_member_required()
def project_list(request: HttpRequest) -> HttpResponse:
    form = ProjectForm(request.POST or None)
    if request.method == "POST":
        if request.membership.role not in _EDITOR_ROLES:  # type: ignore[attr-defined]
            return HttpResponseForbidden("Your role does not permit creating projects.")
        if form.is_valid():
            try:
                project = form.save(commit=False)
                project.owner = request.user
                project.save()
            except IntegrityError:
                form.add_error("key", "A project with this key already exists.")
            else:
                messages.success(request, f"Project {project.key} created.")
                return redirect("portal:project-detail", pk=project.pk)
    projects = Project.objects.select_related("owner").order_by("-created_at")
    return render(request, "portal/project_list.html", {"projects": projects, "form": form})


@tenant_member_required()
def project_detail(request: HttpRequest, pk: int) -> HttpResponse:
    project = get_object_or_404(Project.objects.select_related("owner"), pk=pk)
    form = WorkItemForm(request.POST or None, tenant=request.tenant)
    if request.method == "POST":
        if request.membership.role not in _EDITOR_ROLES:  # type: ignore[attr-defined]
            return HttpResponseForbidden("Your role does not permit creating work items.")
        if form.is_valid():
            item = form.save(commit=False)
            item.project = project
            item.save()
            messages.success(request, f"Work item “{item.title}” added.")
            return redirect("portal:project-detail", pk=project.pk)
    items = project.items.select_related("assignee").order_by("-created_at")
    return render(
        request,
        "portal/project_detail.html",
        {"project": project, "items": items, "form": form,
         "status_choices": WorkItem.Status.choices},
    )


@tenant_member_required(roles=_EDITOR_ROLES)
def work_item_set_status(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("portal:projects")
    item = get_object_or_404(WorkItem.objects.select_related("project"), pk=pk)
    status = request.POST.get("status", "")
    if status in WorkItem.Status.values:
        item.status = status
        item.save(update_fields=["status", "updated_at"])
        messages.success(request, f"“{item.title}” → {item.get_status_display()}.")
    return redirect("portal:project-detail", pk=item.project_id)


@tenant_member_required()
def billing(request: HttpRequest) -> HttpResponse:
    subscription = Subscription.objects.filter(
        status__in=(Subscription.Status.TRIALING, Subscription.Status.ACTIVE)
    ).first()
    form = InvoiceLineForm(request.POST or None)
    if request.method == "POST":
        if request.membership.role not in _ADMIN_ROLES:  # type: ignore[attr-defined]
            return HttpResponseForbidden("Only owners/admins can issue invoices.")
        if subscription is None:
            messages.error(request, "No active subscription to bill against.")
        elif form.is_valid():
            invoice = issue_invoice(
                tenant_id=request.tenant.pk,
                subscription_id=subscription.pk,
                lines=[
                    InvoiceLine(
                        description=form.cleaned_data["description"],
                        amount=form.cleaned_data["amount"],
                    )
                ],
                idempotency_key=uuid.uuid4(),
            )
            messages.success(request, f"Invoice {invoice.number} issued.")
            return redirect("portal:billing")
    invoices = Invoice.objects.prefetch_related("ledger_entries").order_by("-created_at")
    return render(
        request,
        "portal/billing.html",
        {"subscription": subscription, "invoices": invoices, "form": form},
    )


@tenant_member_required(roles=_ADMIN_ROLES)
def invoice_mark_paid(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method == "POST":
        invoice = get_object_or_404(Invoice.objects, pk=pk)
        try:
            mark_invoice_paid(tenant_id=request.tenant.pk, invoice_id=invoice.pk)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Invoice {invoice.number} marked paid.")
    return redirect("portal:billing")


@tenant_member_required()
def member_list(request: HttpRequest) -> HttpResponse:
    form = AddMemberForm(request.POST or None)
    if request.method == "POST":
        if request.membership.role not in _ADMIN_ROLES:  # type: ignore[attr-defined]
            return HttpResponseForbidden("Only owners/admins can add members.")
        if form.is_valid():
            email = form.cleaned_data["email"].lower()
            with transaction.atomic():
                user = User.objects.filter(email=email).first()
                if user is None:
                    user = User.objects.create_user(
                        email, form.cleaned_data["password"]
                    )
                _, created = Membership.objects.get_or_create(
                    user=user,
                    tenant=request.tenant,
                    defaults={"role": form.cleaned_data["role"]},
                )
            if created:
                messages.success(request, f"{email} added as {form.cleaned_data['role']}.")
            else:
                messages.info(request, f"{email} is already a member.")
            return redirect("portal:members")
    memberships = (
        Membership.objects.filter(tenant=request.tenant)
        .select_related("user")
        .order_by("user__email")
    )
    return render(
        request, "portal/members.html", {"memberships": memberships, "form": form}
    )
