from __future__ import annotations

from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.billing"
    verbose_name = "Billing"

    def ready(self) -> None:
        # Connect signal receivers (import side effect, kept out of models).
        from apps.billing import signals  # noqa: F401
