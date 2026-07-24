"""Development settings — NEVER use in any shared or internet-facing
environment.

The dev SECRET_KEY below is intentionally prefixed ``django-insecure-`` so
``manage.py check --deploy`` flags it if this module ever leaks into a
production process.
"""
from __future__ import annotations

from .base import *  # noqa: F403

DEBUG = True

# Development-only key. Production refuses to start without a real key
# supplied via the environment (see production.py).
SECRET_KEY = "django-insecure-dev-only-9f1c2d3e4b5a6978-do-not-deploy"  # noqa: S105 # nosec B105

ALLOWED_HOSTS = ["localhost", "127.0.0.1", ".localtest.me"]
PUBLIC_HOSTS = ["localhost", "127.0.0.1", "localtest.me"]

# Cookies over plain HTTP locally.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Local SQL debugging is acceptable; the PII redaction filter still applies.
LOGGING["loggers"]["django.db.backends"]["level"] = "INFO"  # noqa: F405
