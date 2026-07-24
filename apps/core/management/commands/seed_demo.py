"""Seed a demo tenant with sample data. Idempotent — safe to re-run.

Creates:
- superuser  demo@meridian.dev  (password below — DEMO ONLY)
- tenant     "acme" with domain acme.localtest.me
- OWNER membership, active subscription, project, work items
- one issued + paid invoice with ledger entries (exercises the full
  billing service layer, idempotency keys, and the paid-webhook signal)
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.models import Subscription
from apps.billing.services import InvoiceLine, issue_invoice, mark_invoice_paid
from apps.projects.models import Project, WorkItem
from apps.tenants.context import tenant_context
from apps.tenants.models import Domain, Membership, Tenant

DEMO_EMAIL = "demo@meridian.dev"
# Local demo fixture only — never a production credential.
DEMO_PASSWORD = "demo-Passw0rd-2026"  # noqa: S105 # nosec B105

# Deterministic so re-running the command never double-bills.
_DEMO_INVOICE_KEY = uuid.uuid5(uuid.NAMESPACE_URL, "meridian://demo/invoice/1")


class Command(BaseCommand):
    help = "Create demo tenant (acme.localtest.me), owner user, and sample data."

    def handle(self, *args: Any, **options: Any) -> None:
        user, created = User.objects.get_or_create(
            email=DEMO_EMAIL,
            defaults={"first_name": "Demo", "is_staff": True, "is_superuser": True},
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])

        tenant, _ = Tenant.objects.get_or_create(slug="acme", defaults={"name": "Acme Corp"})
        Domain.objects.get_or_create(
            hostname="acme.localtest.me", defaults={"tenant": tenant, "is_primary": True}
        )
        Membership.objects.get_or_create(
            user=user, tenant=tenant, defaults={"role": Membership.Role.OWNER}
        )

        with tenant_context(tenant.pk):
            now = timezone.now()
            subscription, _ = Subscription.objects.get_or_create(
                status=Subscription.Status.ACTIVE,
                defaults={
                    "plan": Subscription.Plan.GROWTH,
                    "seats": 5,
                    "current_period_start": now,
                    "current_period_end": now + timedelta(days=30),
                },
            )
            project, _ = Project.objects.get_or_create(
                key="CORE", defaults={"name": "Core Platform", "owner": user}
            )
            for title, status in [
                ("Design tenant onboarding flow", WorkItem.Status.IN_PROGRESS),
                ("Rotate webhook signing secrets", WorkItem.Status.BACKLOG),
                ("Ship Q2 usage report", WorkItem.Status.DONE),
            ]:
                WorkItem.objects.get_or_create(
                    project=project, title=title, defaults={"status": status, "assignee": user}
                )

        invoice = issue_invoice(
            tenant_id=tenant.pk,
            subscription_id=subscription.pk,
            lines=[
                InvoiceLine(description="Growth plan — 5 seats", amount=Decimal("245.00")),
                InvoiceLine(description="Additional storage", amount=Decimal("12.50")),
            ],
            idempotency_key=_DEMO_INVOICE_KEY,
        )
        mark_invoice_paid(tenant_id=tenant.pk, invoice_id=invoice.pk)

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"  Admin:   http://localhost:8000/admin/  ({DEMO_EMAIL})")
        self.stdout.write("  API:     http://acme.localtest.me:8000/api/v1/projects/")
        self.stdout.write(f"  Invoice: {invoice.number} (paid, ledger balanced)")
