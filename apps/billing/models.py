"""Billing domain: Subscription, Invoice, append-only LedgerEntry.

Financial integrity rules:

- Money is ``Decimal`` (never float) with DB-level check constraints.
- ``LedgerEntry`` is append-only: updates and deletes raise. Corrections are
  modelled as compensating entries, preserving a complete audit trail.
- One active/trialing subscription per tenant, enforced by a partial unique
  index — not by application code alone.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TenantOwnedModel


class Subscription(TenantOwnedModel):
    class Plan(models.TextChoices):
        FREE = "free", "Free"
        STARTER = "starter", "Starter"
        GROWTH = "growth", "Growth"
        ENTERPRISE = "enterprise", "Enterprise"

    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        CANCELED = "canceled", "Canceled"

    plan = models.CharField(max_length=16, choices=Plan.choices, default=Plan.FREE)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.TRIALING, db_index=True
    )
    seats = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()

    class Meta(TenantOwnedModel.Meta):
        abstract = False
        constraints = [
            models.UniqueConstraint(
                fields=["tenant"],
                condition=models.Q(status__in=("trialing", "active")),
                name="billing_one_live_subscription_per_tenant",
            ),
            models.CheckConstraint(
                condition=models.Q(current_period_end__gt=models.F("current_period_start")),
                name="billing_subscription_period_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.plan}/{self.status} (tenant={self.tenant_id})"


class Invoice(TenantOwnedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPEN = "open", "Open"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    subscription = models.ForeignKey(
        Subscription, on_delete=models.PROTECT, related_name="invoices"
    )
    number = models.CharField(max_length=32)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    currency = models.CharField(max_length=3, default="USD")
    total = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    # Supplied by the caller; the unique index makes retried Celery
    # deliveries and double-clicked buttons idempotent at the DB level.
    idempotency_key = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    issued_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantOwnedModel.Meta):
        abstract = False
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "number"], name="billing_invoice_unique_number_per_tenant"
            ),
            models.CheckConstraint(
                condition=models.Q(total__gte=0), name="billing_invoice_total_non_negative"
            ),
        ]

    def __str__(self) -> str:
        return self.number


class LedgerEntry(TenantOwnedModel):
    """Append-only double-entry ledger line."""

    class Direction(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="ledger_entries"
    )
    direction = models.CharField(max_length=8, choices=Direction.choices)
    amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    memo = models.CharField(max_length=500, blank=True)

    class Meta(TenantOwnedModel.Meta):
        abstract = False
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="billing_ledger_amount_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.direction} {self.amount} ({self.memo})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None and not self._state.adding:
            raise TypeError("LedgerEntry is append-only; create a compensating entry instead.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise TypeError("LedgerEntry is append-only; create a compensating entry instead.")
