"""Demo settings — run the full stack with ZERO external services.

Swaps infrastructure only; every model, manager, permission, and security
control behaves identically to development:

- PostgreSQL → SQLite file        (db.sqlite3)
- Redis cache → local memory      (throttling/domain cache still active)
- Celery broker → eager mode      (tasks execute inline, synchronously)

NEVER deploy this module: SQLite has no row-level locking for concurrent
writers and eager Celery hides queue failures.
"""
from __future__ import annotations

from .development import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "meridian-demo",
    }
}

# Sessions: plain DB backend (no shared cache worth using here).
SESSION_ENGINE = "django.contrib.sessions.backends.db"

# Celery tasks run inline in the calling process.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
