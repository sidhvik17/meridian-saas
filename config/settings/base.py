"""Base settings shared by every environment.

Environment-specific modules (``development``, ``production``) star-import
from this module and override what differs. No secret value is ever
hardcoded here: secrets come exclusively from the process environment.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured

BASE_DIR: Final[Path] = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Environment helpers (typed, fail-fast)
# ---------------------------------------------------------------------------

_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})


def env_str(name: str, default: str | None = None) -> str:
    """Return an environment variable, raising if absent with no default."""
    value = os.environ.get(name, default)
    if value is None:
        raise ImproperlyConfigured(f"Required environment variable {name!r} is not set.")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable ('1', 'true', 'yes', 'on')."""
    return os.environ.get(name, str(default)).strip().lower() in _TRUTHY


def env_int(name: str, default: int) -> int:
    """Parse an integer environment variable, raising on malformed input."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"Environment variable {name!r} must be an integer.") from exc


def env_list(name: str, default: str = "") -> list[str]:
    """Parse a comma-separated environment variable into a list."""
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

# SECRET_KEY is intentionally NOT defined here. Each environment module must
# set it explicitly (production reads it from the environment and fails hard
# if missing). DEBUG defaults to False so a misconfigured deployment fails
# safe rather than leaking stack traces.
DEBUG: bool = False

ALLOWED_HOSTS: list[str] = env_list("DJANGO_ALLOWED_HOSTS")

# Hosts that serve non-tenant pages (marketing site, admin, health checks).
# TenantResolutionMiddleware skips tenant binding for these.
PUBLIC_HOSTS: list[str] = env_list("DJANGO_PUBLIC_HOSTS", "localhost,127.0.0.1")

# Path prefix for the Django admin, configurable per deployment so the admin
# does not live at the universally scanned default in production.
ADMIN_URL: str = env_str("DJANGO_ADMIN_URL", "admin/")

INSTALLED_APPS: list[str] = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    # First-party
    "apps.core",
    "apps.accounts",
    "apps.tenants",
    "apps.projects",
    "apps.billing",
    "apps.portal",
]

MIDDLEWARE: list[str] = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Tenant resolution runs after auth so views see both request.user and
    # request.tenant; it binds the tenant ContextVar for the ORM layer.
    "apps.tenants.middleware.TenantResolutionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF: str = "config.urls"

TEMPLATES: list[dict[str, Any]] = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION: str = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database — PostgreSQL only (no SQLite fallback in any shared environment)
# ---------------------------------------------------------------------------

DATABASES: dict[str, dict[str, Any]] = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_str("POSTGRES_DB", "meridian"),
        "USER": env_str("POSTGRES_USER", "meridian"),
        "PASSWORD": env_str("POSTGRES_PASSWORD", ""),
        "HOST": env_str("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env_str("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 60),
        "OPTIONS": {
            # 'require' (or stronger) in production; enforced in production.py.
            "sslmode": env_str("DB_SSLMODE", "prefer"),
        },
    },
}

DEFAULT_AUTO_FIELD: str = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Authentication & passwords
# ---------------------------------------------------------------------------

AUTH_USER_MODEL: str = "accounts.User"

LOGIN_URL: str = "/accounts/login/"
LOGIN_REDIRECT_URL: str = "/dashboard/"
LOGOUT_REDIRECT_URL: str = "/accounts/login/"

# Argon2id first: memory-hard, the current best practice. PBKDF2 hashers are
# retained so existing hashes verify and transparently upgrade on next login.
PASSWORD_HASHERS: list[str] = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS: list[dict[str, Any]] = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# ---------------------------------------------------------------------------
# Sessions & CSRF
# ---------------------------------------------------------------------------

SESSION_ENGINE: str = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_HTTPONLY: bool = True
SESSION_COOKIE_SAMESITE: str = "Lax"
SESSION_COOKIE_AGE: int = 60 * 60 * 12  # 12 hours
SESSION_EXPIRE_AT_BROWSER_CLOSE: bool = True

CSRF_COOKIE_SAMESITE: str = "Lax"
# The CSRF token is delivered to templates via {% csrf_token %} and to the
# SPA via a meta tag, so JavaScript never needs to read the cookie itself.
CSRF_COOKIE_HTTPONLY: bool = True

# ---------------------------------------------------------------------------
# Cache & Redis
# ---------------------------------------------------------------------------

REDIS_URL: str = env_str("REDIS_URL", "redis://127.0.0.1:6379/0")

CACHES: dict[str, dict[str, Any]] = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "TIMEOUT": 300,
        "KEY_PREFIX": "meridian",
    },
}

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK: dict[str, Any] = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Deny-by-default: every endpoint must opt IN to wider access.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.core.throttling.BurstRateThrottle",
        "apps.core.throttling.SustainedRateThrottle",
        "apps.core.throttling.TenantRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "burst": "60/min",
        "sustained": "1000/day",
        "tenant": "10000/day",
    },
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

# ---------------------------------------------------------------------------
# Celery (JSON-only serialization; pickle is never accepted)
# ---------------------------------------------------------------------------

CELERY_BROKER_URL: str = env_str("CELERY_BROKER_URL", "redis://127.0.0.1:6379/1")
CELERY_RESULT_BACKEND: str = env_str("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/2")
CELERY_TASK_SERIALIZER: str = "json"
CELERY_RESULT_SERIALIZER: str = "json"
CELERY_ACCEPT_CONTENT: list[str] = ["json"]
CELERY_TASK_ACKS_LATE: bool = True
CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1
CELERY_TASK_TIME_LIMIT: int = 300
CELERY_TASK_SOFT_TIME_LIMIT: int = 240
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP: bool = True

# ---------------------------------------------------------------------------
# Internationalisation / static files
# ---------------------------------------------------------------------------

LANGUAGE_CODE: str = "en-us"
TIME_ZONE: str = "UTC"
USE_I18N: bool = True
USE_TZ: bool = True

STATIC_URL: str = "static/"
STATIC_ROOT: Path = BASE_DIR / "static"
STORAGES: dict[str, dict[str, str]] = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Hard caps on request bodies to blunt memory-exhaustion abuse.
DATA_UPLOAD_MAX_MEMORY_SIZE: int = 5 * 1024 * 1024  # 5 MiB
FILE_UPLOAD_MAX_MEMORY_SIZE: int = 5 * 1024 * 1024

# ---------------------------------------------------------------------------
# Logging — console JSON-ish logs with PII redaction on every handler
# ---------------------------------------------------------------------------

LOGGING: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact_pii": {"()": "apps.core.logging.RedactPIIFilter"},
    },
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["redact_pii"],
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env_str("DJANGO_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django.security": {"level": "WARNING"},
        # Never log SQL (could contain PII) outside local development.
        "django.db.backends": {"level": "ERROR"},
    },
}
