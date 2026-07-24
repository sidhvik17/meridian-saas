"""Signal receivers for billing events."""
from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.billing.models import Invoice


@receiver(post_save, sender=Invoice, dispatch_uid="billing.invoice_paid_webhook")
def enqueue_invoice_paid_webhook(
    sender: type[Invoice], instance: Invoice, created: bool, **kwargs: Any
) -> None:
    """Queue webhook delivery when an invoice transitions to PAID.

    ``transaction.on_commit`` ensures the task is enqueued only if the
    surrounding transaction commits — a rolled-back payment can never emit
    an 'invoice.paid' event.
    """
    if instance.status != Invoice.Status.PAID or instance.paid_at is None:
        return

    from apps.billing.tasks import send_invoice_paid_webhook

    transaction.on_commit(
        lambda: send_invoice_paid_webhook.delay(
            tenant_id=instance.tenant_id, invoice_id=instance.pk
        )
    )
