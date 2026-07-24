"""Project configuration package.

Importing the Celery app here ensures ``shared_task`` decorators bind to it
when Django starts.
"""
from __future__ import annotations

from .celery import app as celery_app

__all__ = ["celery_app"]
