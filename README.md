# Meridian — Multi-Tenant B2B SaaS Platform

A production-grade, multi-tenant work-management and billing platform built on
Django 5.2 LTS. Each customer (tenant) is served from its own subdomain
(`acme.meridian.app`), with strict row-level data isolation enforced at the ORM
layer, asynchronous billing via Celery, and Redis-backed caching and API
throttling.

## Documents

| File | Purpose |
|------|---------|
| [WALKTHROUGH.md](WALKTHROUGH.md) | **Start here** — what the project is, complete code tour |
| [SETUP_GUIDE.md](SETUP_GUIDE.md) | How to run (demo/dev/prod) and what to integrate |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture, data models, API boundaries |
| [SECURITY_AUDIT.md](SECURITY_AUDIT.md) | Full security audit and remediation report |

## Stack

- **Django 5.2 LTS** (custom user model, custom managers, signals, mixins)
- **Django REST Framework** (versioned JSON API, object-level permissions)
- **PostgreSQL 16** via `psycopg` 3 (row-level tenant isolation, DB constraints)
- **Celery 5 + Redis** (invoice generation, webhook delivery)
- **Redis** (cache, session backend support, API throttling)
- **Argon2** password hashing

## Quick start (demo — zero external services)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\base.txt
$env:DJANGO_SETTINGS_MODULE = "config.settings.demo"
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver
```

Then: admin at `http://localhost:8000/admin/` (`demo@meridian.dev` /
`demo-Passw0rd-2026`), tenant API at
`http://acme.localtest.me:8000/api/v1/projects/`. Full instructions incl.
PostgreSQL/Redis development setup: [SETUP_GUIDE.md](SETUP_GUIDE.md).

Tenant subdomains resolve locally via `*.localtest.me` (which points to
127.0.0.1), e.g. `http://acme.localtest.me:8000/`.

## Production

```bash
export DJANGO_SETTINGS_MODULE=config.settings.production
python manage.py check --deploy        # must pass with zero warnings
gunicorn config.wsgi:application
celery -A config worker -l info
```

All secrets are supplied via environment variables — see `.env.example`.
Never commit a real `.env` file.
