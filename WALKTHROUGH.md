# Meridian — Complete Code Walkthrough

This document explains **what the project is**, how every piece fits
together, and what happens — file by file — when a request hits the
platform. Companion docs: [SETUP_GUIDE.md](SETUP_GUIDE.md) (how to run and
what to integrate), [ARCHITECTURE.md](ARCHITECTURE.md) (design rationale),
[SECURITY_AUDIT.md](SECURITY_AUDIT.md) (vulnerability log).

---

## 1. What is this project?

**Meridian is a multi-tenant B2B SaaS platform** — think "Jira + Stripe
billing in one codebase". Companies (*tenants*) sign up, get their own
subdomain, and manage projects and work items there, while the platform
bills them through a subscription/invoice/ledger pipeline.

| Concept | Real-world meaning | Example |
|---------|-------------------|---------|
| **Tenant** | A customer company | Acme Corp |
| **Domain** | The subdomain that routes to a tenant | `acme.meridian.app` |
| **Membership** | A user's role inside a tenant | demo@… is OWNER of Acme |
| **Project / WorkItem** | The product itself (work management) | "Core Platform" / tasks |
| **Subscription / Invoice / LedgerEntry** | How the platform makes money | Growth plan, INV-000001-000001 |

One codebase, one database — but every row of customer data carries a
`tenant_id`, and three independent layers make it (provably, via tests)
impossible for tenant A to read tenant B's data. That isolation problem is
the heart of the project; almost every interesting file exists to serve it.

**Verified working** (2026-06-10, Windows, Python 3.12.10, demo settings):
migrations apply, all 7 isolation tests pass, server boots, session login
works, authenticated tenant API returns seeded data, unknown subdomains 404.

---

## 2. Directory map

```
Django_final_project/
├── manage.py                    CLI entry; defaults to development settings
├── pyproject.toml               ruff / mypy(strict) / bandit / pytest config
├── requirements/                pinned deps: base / development / production
├── .env.example                 every env var documented, no real values
│
├── config/                      "the project" (vs. "the apps")
│   ├── settings/
│   │   ├── base.py              shared settings + typed env helpers
│   │   ├── development.py       DEBUG=True, dev-only key, localtest.me hosts
│   │   ├── production.py        hardened; refuses to boot if misconfigured
│   │   └── demo.py              SQLite + locmem + eager Celery (zero services)
│   ├── urls.py                  admin (env path) + /api/v1/ + /healthz/
│   ├── celery.py                Celery app; reads CELERY_* from Django settings
│   ├── wsgi.py / asgi.py        server entry points
│   └── __init__.py              exposes celery_app so @shared_task binds
│
├── apps/
│   ├── core/                    shared building blocks
│   │   ├── models.py            TimeStampedModel, TenantOwnedModel  ← keystone
│   │   ├── throttling.py        burst / sustained / per-tenant API throttles
│   │   ├── logging.py           RedactPIIFilter (emails, tokens → [REDACTED])
│   │   ├── views.py             /healthz/ liveness probe
│   │   └── management/commands/seed_demo.py   demo data seeder
│   ├── accounts/                custom User (email login, Argon2)
│   ├── tenants/                 THE isolation machinery
│   │   ├── context.py           ContextVar tenant binding
│   │   ├── managers.py          fail-closed TenantAwareManager
│   │   ├── middleware.py        Host → Domain → Tenant resolution
│   │   ├── models.py            Tenant, Domain, Membership
│   │   └── tests/test_isolation.py   security regression suite
│   ├── projects/                product domain + REST API
│   │   ├── models.py            Project, WorkItem
│   │   └── api/                 serializers, permissions, viewsets, router
│   ├── portal/                  server-rendered UI (no models)
│   │   ├── views.py             dashboard/projects/billing/members pages
│   │   └── forms.py             project, work item, add-member, invoice forms
│   └── billing/                 money
│       ├── models.py            Subscription, Invoice, append-only LedgerEntry
│       ├── services.py          the ONLY sanctioned invoice write path
│       ├── tasks.py             Celery: issue invoice, send paid-webhook
│       ├── signals.py           Invoice PAID → enqueue webhook (on_commit)
│       └── webhooks.py          SSRF-guarded, HMAC-signed delivery
│
├── templates/                   base layout + login + portal pages
└── scripts/                     demo_api_check.py, demo_ui_check.py smoke tests
```

---

## 3. The settings story (`config/settings/`)

`base.py` defines typed helpers (`env_str`, `env_bool`, `env_int`,
`env_list`) that raise `ImproperlyConfigured` instead of limping along with
a bad value. Everything security-relevant funnels through them.

Four modules, one inheritance chain:

- **base.py** — apps, middleware order, Argon2 password hashers, DRF
  defaults (deny-by-default permissions, JSON-only renderer, three throttle
  scopes), Celery JSON-only serialization, Redis cache, PII-redacting
  logging. `DEBUG = False` here on purpose: forgetting to override fails
  *safe*.
- **development.py** — `DEBUG=True`, a deliberately `django-insecure-`
  prefixed key, `.localtest.me` hosts (wildcard DNS → 127.0.0.1).
- **production.py** — refuses to boot if `DJANGO_SECRET_KEY` is missing,
  short, or a dev key; refuses empty `ALLOWED_HOSTS`; forces SSL redirect,
  HSTS (1 year, preload, subdomains), secure cookies, TLS to Postgres.
- **demo.py** — used for the verified run on this machine: swaps Postgres →
  SQLite, Redis → local-memory cache, Celery → eager (inline) execution.
  Infrastructure changes; *behaviour doesn't* — same managers, permissions,
  throttles, signals.

Middleware order matters and is deliberate:

```
SecurityMiddleware → WhiteNoise → Session → Common → CSRF → Auth
→ TenantResolutionMiddleware → Messages → XFrameOptions
```

Tenant resolution sits **after** auth (so views get both `request.user` and
`request.tenant`) and after Django has already validated the Host header
against `ALLOWED_HOSTS`.

---

## 4. Life of a request

`GET https://acme.meridian.app/api/v1/projects/` — step by step:

1. **Host validation** (Django core). `acme.meridian.app` must match
   `ALLOWED_HOSTS = ['.meridian.app']`, else `DisallowedHost`. Forged Host
   headers die here.
2. **Tenant resolution**
   ([apps/tenants/middleware.py](apps/tenants/middleware.py)).
   - `/healthz/` and public hosts (`meridian.app`) skip tenancy.
   - Otherwise: Redis cache lookup `tenant:domain:acme.meridian.app`; on
     miss, exact-match query against `Domain` (hostnames stored lowercase,
     regex-validated). Unknown host → uniform 404 (no "tenant exists"
     signal; negative results cached to blunt enumeration sweeps).
   - On hit: `request.tenant = <Acme>`, and the tenant id is bound to a
     `ContextVar` ([context.py](apps/tenants/context.py)) — async-safe,
     always unbound in `finally` so worker reuse can't leak scope.
3. **DRF permission stack**
   ([apps/projects/api/permissions.py](apps/projects/api/permissions.py)):
   - `IsAuthenticated` — who are you?
   - `IsTenantMember` — do you hold an *active* `Membership` in Acme?
     (Being logged in grants nothing tenant-wise.)
   - `RoleBasedWritePermission` — GET for any member; POST/PUT for
     owner/admin/member; DELETE for owner/admin only.
4. **The query** ([apps/projects/api/views.py](apps/projects/api/views.py)).
   `Project.objects.all()` is *already filtered* to Acme — `objects` is the
   fail-closed `TenantAwareManager`. The view physically cannot ask an
   unscoped question.
5. **Object access** (detail routes). Even after the scoped 404-on-foreign-id,
   `has_object_permission` re-compares `obj.tenant_id == request.tenant.pk`.
6. **Serialization** — explicit field lists only (`fields = "__all__"` is
   banned project-wide), JSON renderer only.
7. **Throttles** — 60/min burst + 1000/day per user + 10000/day per tenant.

Live results from the verified run:

| Probe | Result |
|-------|--------|
| `/healthz/` (public host) | 200 |
| `/api/v1/projects/` unauthenticated, real tenant | 403 (tenant resolved → auth layer rejected) |
| `/api/v1/projects/` on `ghost.localtest.me` | 404 (anti-enumeration) |
| Session login then `/api/v1/projects/` | 200 — `{"count":1,...Core Platform...}` |
| `/api/v1/work-items/` authenticated | 200 — 3 seeded items |

---

## 5. The isolation keystone

Three files do the heavy lifting:

**[apps/tenants/context.py](apps/tenants/context.py)** — a
`ContextVar[int | None]` holding the active tenant id, plus
`tenant_context(tenant_id)` for `with`-block binding. ContextVars (unlike
thread-locals) behave correctly under both threaded WSGI and async ASGI.

**[apps/tenants/managers.py](apps/tenants/managers.py)** — the single most
important security control:

```python
def get_queryset(self):
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise TenantContextError(...)      # fail CLOSED
    return super().get_queryset().filter(tenant_id=tenant_id)
```

No bound tenant → exception, never "all rows". System code (Celery,
management commands) uses the greppable escape hatch
`Model.objects.for_tenant(id)` or `tenant_context(...)`.

**[apps/core/models.py](apps/core/models.py)** — `TenantOwnedModel`, the
abstract base every customer-data model inherits. It wires the scoped
manager as the default, keeps an `unscoped` manager for Django internals
(`base_manager_name`), and overrides `save()` to inject the bound tenant —
so *writes* can't cross tenants either.

Proof lives in
[apps/tenants/tests/test_isolation.py](apps/tenants/tests/test_isolation.py)
(7 tests, all passing): unscoped queries raise; pk lookups can't cross
tenants (IDOR); saves without context raise; context resets after blocks;
unknown hosts 404.

---

## 6. Accounts, projects, billing — the domains

**accounts/** — custom `User`: email is the username (case-insensitively
unique via a `Lower("email")` constraint), Argon2id hashing, typed
`UserManager` with `create_user`/`create_superuser`. No tenant FK on User —
tenancy is many-to-many through `Membership`, so one human can belong to
several companies with different roles.

**projects/** — `Project` (key unique *per tenant*, so uniqueness errors
can't leak other tenants' keys) and `WorkItem` (status workflow, assignee).
The API layer adds two subtle IDOR guards: `WorkItemSerializer.project`
uses a tenant-scoped `PrimaryKeyRelatedField` (you can't attach an item to
a foreign project by guessing ids), and `validate_assignee` rejects
non-members.

**billing/** — the money pipeline, built around financial-integrity rules:

- [models.py](apps/billing/models.py): `Decimal(18,4)` everywhere (never
  float); DB check constraints (`amount > 0`, `total >= 0`, period
  validity); partial unique index = max one live subscription per tenant;
  `LedgerEntry.save()/delete()` raise on mutation — corrections are
  compensating entries, preserving the audit trail.
- [services.py](apps/billing/services.py): the *only* sanctioned write
  path. `issue_invoice` runs in `transaction.atomic()` with
  `select_for_update()` on the subscription (no duplicate-number races) and
  a DB-unique `idempotency_key` (Celery redelivery or a double-click
  returns the existing invoice instead of double-billing).
- [signals.py](apps/billing/signals.py): when an invoice transitions to
  PAID, a `post_save` receiver enqueues the webhook via
  `transaction.on_commit` — a rolled-back payment can never emit an event.
- [tasks.py](apps/billing/tasks.py): Celery tasks take JSON-safe args only
  (`Decimal` as string), receive an explicit `tenant_id`, and bind context
  themselves; `acks_late` + idempotent bodies make crash-redelivery safe.
- [webhooks.py](apps/billing/webhooks.py): outbound delivery is
  SSRF-guarded (https only, port 443, no IP literals, no credentials, no
  redirects, 10 s timeout) and HMAC-SHA256 signed with per-tenant secrets.

The whole chain was exercised live by `seed_demo`: issue → ledger debit
entries → mark paid → credit entry → signal → eager webhook task ran.

---

## 7. Demo data & smoke checks

- `manage.py seed_demo`
  ([apps/core/management/commands/seed_demo.py](apps/core/management/commands/seed_demo.py))
  — idempotent seeder: superuser `demo@meridian.dev`, tenant **acme** with
  domain `acme.localtest.me`, OWNER membership, active Growth subscription,
  project + 3 work items, one issued-and-paid invoice
  (`INV-000001-000001`). The invoice idempotency key is a deterministic
  UUIDv5, so re-running never double-bills.
- [scripts/demo_api_check.py](scripts/demo_api_check.py) — real-HTTP smoke
  test: fetches the login form, performs the CSRF dance, logs in, calls
  both API endpoints as an authenticated member. Run it any time the demo
  server is up.

---

## 8. Where to extend

- **New tenant-owned model** → inherit `TenantOwnedModel`; isolation, audit
  timestamps, and write-scoping come free. Add a `(tenant, …)` unique
  constraint instead of a global one.
- **New API endpoint** → viewset + `TenantScopedViewSetMixin`
  ([views.py](apps/projects/api/views.py)); enumerate serializer fields
  explicitly; register on the router.
- **New background job** → `@shared_task` with JSON-safe kwargs including
  `tenant_id`; first line of the body enters `tenant_context(tenant_id)`.
- **Security roadmap** (open items from the audit): `django-axes` lockout +
  TOTP MFA (V-07), egress proxy for webhook DNS-rebinding (V-08),
  `django-csp` nonce policy (V-15).
