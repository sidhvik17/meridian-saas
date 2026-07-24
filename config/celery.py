"""Celery application entry point.

Run a worker with::

    celery -A config worker -l info
"""
from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

app = Celery("meridian")

# All Celery settings live in Django settings under the CELERY_ namespace so
# there is exactly one place to audit broker/serializer configuration.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
