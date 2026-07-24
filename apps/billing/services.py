"""Billing service layer — the only sanctioned write path for invoices.

Views and tasks call these functions; they never manipulate billing models
directly. This concentrates the financial invariants (atomicity, locking,
idempotency) in one auditable module.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.models import Invoice, LedgerEntry, Subscription
from apps.tenants.context import tenant_context


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    """One billable line. Validated on construction."""

    description: str
    amount: Decimal

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError("Invoice line amount must be positive.")
        if not self.description.strip():
            raise ValueError("Invoice line description is required.")


def issue_invoice(
    *,
    tenant_id: int,
    subscription_id: int,
    lines: list[InvoiceLine],
    idempotency_key: uuid.UUID,
) -> Invoice:
    """Issue an invoice for a subscription, atomically and idempotently.

    - ``select_for_update`` on the subscription serialises concurrent
      issuance for the same subscription (no duplicate numbers, no races).
    - The ``idempotency_key`` short-circuits retries: a Celery redelivery or
      a double-submitted request returns the already-created invoice.
    """
    if not lines:
        raise ValueError("An invoice requires at least one line.")

    with tenant_context(tenant_id), transaction.atomic():
        existing = Invoice.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing

        subscription = Subscription.objects.select_for_update().get(pk=subscription_id)

        total = sum((line.amount for line in lines), Decimal("0"))
        invoice = Invoice.objects.create(
            subscription=subscription,
            number=_next_invoice_number(subscription),
            status=Invoice.Status.OPEN,
            total=total,
            idempotency_key=idempotency_key,
            issued_at=timezone.now(),
        )
        LedgerEntry.objects.bulk_create(
            [
                LedgerEntry(
                    tenant_id=tenant_id,
                    invoice=invoice,
                    direction=LedgerEntry.Direction.DEBIT,
                    amount=line.amount,
                    memo=line.description[:500],
                )
                for line in lines
            ]
        )
        return invoice


def mark_invoice_paid(*, tenant_id: int, invoice_id: int) -> Invoice:
    """Transition an invoice to PAID with a credit ledger entry."""
    with tenant_context(tenant_id), transaction.atomic():
        invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
        if invoice.status == Invoice.Status.PAID:
            return invoice  # Idempotent: repeated payment callbacks are no-ops.
        if invoice.status != Invoice.Status.OPEN:
            raise ValueError(f"Cannot pay an invoice in status {invoice.status!r}.")

        LedgerEntry.objects.create(
            invoice=invoice,
            direction=LedgerEntry.Direction.CREDIT,
            amount=invoice.total,
            memo=f"Payment for {invoice.number}",
        )
        invoice.status = Invoice.Status.PAID
        invoice.paid_at = timezone.now()
        invoice.save(update_fields=["status", "paid_at", "updated_at"])
        return invoice


def _next_invoice_number(subscription: Subscription) -> str:
    """Sequential per-tenant invoice number.

    Safe because callers hold a row lock on the subscription, serialising
    issuance per subscription; the (tenant, number) unique constraint backs
    this up at the DB level.
    """
    count = Invoice.objects.filter(subscription=subscription).count()
    return f"INV-{subscription.tenant_id:06d}-{count + 1:06d}"
