# Meridian — Setup & Integration Guide

How to run the project in three modes, from "zero services, 5 commands"
to full production. Every command in §1 was executed and verified on
Windows 11 / Python 3.12.10 / PowerShell on 2026-06-10.

| Mode | Settings module | Needs | Use for |
|------|----------------|-------|---------|
| **Demo** | `config.settings.demo` | nothing (SQLite, in-memory cache, inline Celery) | trying it right now |
| **Development** | `config.settings.development` | PostgreSQL + Redis | real feature work |
| **Production** | `config.settings.production` | PostgreSQL + Redis + secrets + TLS proxy | deployment |

---

## 1. Demo mode — verified, zero external services

From the project root (`Django_final_project/`), PowerShell:

```powershell
# 1. Virtual environment + dependencies
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\base.txt

# 2. Point Django at the demo settings (this shell only)
$env:DJANGO_SETTINGS_MODULE = "config.settings.demo"

# 3. Create the schema (SQLite file db.sqlite3 appears in the project root)
.\.venv\Scripts\python.exe manage.py migrate

# 4. Seed the demo tenant, user, project, and a paid invoice
.\.venv\Scripts\python.exe manage.py seed_demo

# 5. Run the security regression suite (7 tests — must all pass)
.\.venv\Scripts\python.exe manage.py test apps.tenants -v 2

# 6. Start the server
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Then explore:

| URL | What you get |
|-----|--------------|
| `http://localhost:8000/` | public landing page |
| `http://acme.localtest.me:8000/` | **tenant portal** — login `demo@meridian.dev` / `demo-Passw0rd-2026`, then dashboard, projects, work items, billing (issue/pay invoices), members (add users) |
| `http://localhost:8000/admin/` | Django admin (same credentials) |
| `http://localhost:8000/healthz/` | `{"status": "ok"}` |
| `http://acme.localtest.me:8000/api/v1/projects/` | tenant JSON API (uses the same session) |
| `http://ghost.localtest.me:8000/` | 404 — unknown tenant, by design |

`*.localtest.me` is public wildcard DNS that always resolves to 127.0.0.1 —
that's how subdomain tenancy works on your laptop with zero hosts-file
editing. (Offline? Add `127.0.0.1 acme.localtest.me` to
`C:\Windows\System32\drivers\etc\hosts`.)

Automated end-to-end checks (server must be running, second terminal):

```powershell
.\.venv\Scripts\python.exe scripts\demo_api_check.py   # API: login + JSON endpoints
.\.venv\Scripts\python.exe scripts\demo_ui_check.py    # UI: login + every page + create member/project/work item
```

**Demo-mode caveats:** SQLite tolerates `select_for_update` silently
(no real row locks) and eager Celery hides queue failures. Fine for
exploring; never for deployment.

---

## 2. Development mode — what to integrate and how

### 2.1 PostgreSQL 16

Pick one:

- **Docker (recommended):**
  ```powershell
  docker run -d --name meridian-pg -p 5432:5432 `
    -e POSTGRES_DB=meridian -e POSTGRES_USER=meridian `
    -e POSTGRES_PASSWORD=devpassword postgres:16
  ```
- **Windows installer:** enterprisedb.com → PostgreSQL 16 → create database
  `meridian` and role `meridian` with a password.

### 2.2 Redis 7

Redis has no official Windows build. Options:

- **Docker:** `docker run -d --name meridian-redis -p 6379:6379 redis:7`
- **WSL2:** `sudo apt install redis-server && sudo service redis-server start`
- **Memurai** (Windows-native Redis-compatible) if Docker/WSL unavailable.

### 2.3 Environment

```powershell
copy .env.example .env    # then edit
```

Minimum for development (set in the shell or via your process manager —
Django reads the process environment; .env loading is your runner's job,
e.g. VS Code envFile, direnv, or docker-compose `env_file`):

```powershell
$env:DJANGO_SETTINGS_MODULE = "config.settings.development"
$env:POSTGRES_DB = "meridian"; $env:POSTGRES_USER = "meridian"
$env:POSTGRES_PASSWORD = "devpassword"; $env:POSTGRES_HOST = "127.0.0.1"
$env:DB_SSLMODE = "prefer"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
$env:CELERY_BROKER_URL = "redis://127.0.0.1:6379/1"
$env:CELERY_RESULT_BACKEND = "redis://127.0.0.1:6379/2"
```

### 2.4 Run everything

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements\development.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver
```

Celery worker — second terminal (`--pool=solo` is required on Windows;
Linux/macOS omit it):

```powershell
$env:DJANGO_SETTINGS_MODULE = "config.settings.development"
.\.venv\Scripts\celery.exe -A config worker -l info --pool=solo
```

Quality gates (same commands CI runs):

```powershell
.\.venv\Scripts\python.exe manage.py test          # full suite
.\.venv\Scripts\ruff.exe check .                   # lint incl. security (S) rules
.\.venv\Scripts\mypy.exe apps config               # strict typing
.\.venv\Scripts\bandit.exe -r apps config -c pyproject.toml
.\.venv\Scripts\pip-audit.exe -r requirements\production.txt
```

---

## 3. Production — integration checklist

Read [SECURITY_AUDIT.md](SECURITY_AUDIT.md) §6 first; these are enforced at
boot, not suggestions.

### 3.1 Required environment

| Variable | Value | Boot-enforced |
|----------|-------|---------------|
| `DJANGO_SETTINGS_MODULE` | `config.settings.production` | — |
| `DJANGO_SECRET_KEY` | ≥ 50 random chars from a secret manager | yes — short/dev keys refused |
| `DJANGO_ALLOWED_HOSTS` | `.meridian.app` (your apex + wildcard) | yes — empty refused |
| `DJANGO_PUBLIC_HOSTS` | `meridian.app,www.meridian.app` | — |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://*.meridian.app` | — |
| `DJANGO_ADMIN_URL` | non-default path, e.g. `ops-console-7f3a/` | — |
| `POSTGRES_*` | managed Postgres, TLS on | `DB_SSLMODE=disable/allow` refused |
| `REDIS_URL`, `CELERY_*` | private-network Redis **with AUTH** | — |
| `DJANGO_BEHIND_TLS_PROXY` | `true` **only** if your proxy overwrites `X-Forwarded-Proto` on every request | — |

Generate the key:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

### 3.2 Deploy steps

```bash
pip install -r requirements/production.txt
python manage.py check --deploy --fail-level WARNING   # zero tolerance
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --workers 4 --bind 0.0.0.0:8000
celery -A config worker -l info --concurrency 4        # separate process/host
```

### 3.3 Platform wiring

- **DNS:** apex + `*.meridian.app` wildcard → load balancer.
- **TLS:** wildcard certificate; proxy terminates TLS and **overwrites**
  `X-Forwarded-Proto` (if it merely forwards it, clients can spoof https —
  see SECURITY_AUDIT.md V-06).
- **Tenant onboarding:** create `Tenant` + `Domain` rows (admin or shell);
  the resolution cache picks new domains up within 300 s, or
  `cache.delete(f"tenant:domain:{host}")` for instant.
- **CI gates per merge:** full test suite (isolation tests are
  ship-blockers), `ruff`, `mypy`, `bandit`, `pip-audit`,
  `check --deploy --fail-level WARNING`.
- **Security roadmap** (audit V-07/V-08/V-15): `django-axes` lockout, TOTP
  MFA for admins, webhook egress proxy, `django-csp`.

---

## 4. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `ImproperlyConfigured: Required environment variable 'DJANGO_SECRET_KEY'` | You're on production settings without the env var — intended fail-safe. Set the var or switch module. |
| `TenantContextError: ... queried without a bound tenant` | You queried a tenant-owned model from a shell/task without binding. Wrap in `tenant_context(tenant_id)` — this error existing is the security model working. |
| 404 on a tenant subdomain that should exist | No `Domain` row for that exact lowercase hostname, or tenant `is_active=False`. Check admin → Domains; remember the 300 s negative cache. |
| `DisallowedHost` | Host missing from `ALLOWED_HOSTS` for the active settings module. |
| pip `ResolutionImpossible` on celery/redis | Don't pin `redis` separately; the `celery[redis]` extra governs the client version (already fixed in `requirements/base.txt`). |
| Celery worker hangs/crashes on Windows | Add `--pool=solo` (Windows lacks fork). |
| Port 8000 busy | `runserver 127.0.0.1:8001` or stop the other process. |
