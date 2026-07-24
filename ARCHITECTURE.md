# Meridian — System Architecture

**Phase 1 deliverable** — project selection, system architecture, data models,
and API boundaries.

## 1. Project selection

**Meridian** is a multi-tenant B2B SaaS platform for work management with
integrated subscription billing. It was selected because it exercises every
advanced Django pattern demanded of an enterprise system:

- **Dynamic subdomain tenancy** — `acme.meridian.app` resolves to tenant
  *Acme* at the middleware layer; all data access is row-level isolated.
- **Custom user model** — email-based authentication, Argon2 hashing.
- **Advanced ORM** — fail-closed custom managers, `ContextVar`-bound tenant
  scoping, DB-level constraints (partial unique indexes, check constraints),
  `select_for_update` for financial integrity.
- **Asynchronous processing** — Celery workers generate invoices and deliver
  HMAC-signed webhooks; Redis is the broker and result backend.
- **Caching & throttling** — Redis-backed domain-resolution cache and
  three-tier DRF throttling (user burst, user sustained, per-tenant).

## 2. Tenancy model

**Shared database, shared schema, row-level isolation.** Every tenant-owned
row carries a `tenant_id` foreign key. Isolation is enforced in *three*
independent layers (defense in depth):

1. **Middleware** — `TenantResolutionMiddleware` maps `Host` → `Domain` →
   `Tenant`, binds the tenant id into a `contextvars.ContextVar`, and rejects
   unknown hosts with 404. Django's `ALLOWED_HOSTS` validation runs first, so
   forged `Host` headers never reach tenant resolution.
2. **ORM** — `TenantAwareManager` is the *default* manager on every
   tenant-owned model. It filters every queryset by the bound tenant and
   **fails closed**: querying without a bound tenant raises
   `TenantContextError` instead of returning cross-tenant rows. System code
   (Celery, management commands) must opt in explicitly via
   `Model.objects.for_tenant(...)` or `tenant_context(...)`.
3. **API** — DRF permission classes verify the requesting user holds an
   active `Membership` in the resolved tenant, with role checks per HTTP
   method and object-level tenant comparison.

Trade-off note: schema-per-tenant (e.g. `django-tenants`) gives stronger
physical isolation but complicates migrations and connection pooling at scale.
Row-level isolation with fail-closed managers was chosen for operational
simplicity; the audit (SECURITY_AUDIT.md §V-01) documents the residual risk
and the compensating controls.

## 3. Component diagram

```
                ┌────────────────────────────────────────────────┐
                │                  CDN / WAF                     │
                └───────────────────────┬────────────────────────┘
                                        │ TLS (terminated at LB)
                ┌───────────────────────▼────────────────────────┐
                │   Load balancer  (sets X-Forwarded-Proto)      │
                └───────────────────────┬────────────────────────┘
                                        │
       ┌────────────────────────────────▼─────────────────────────────┐
       │  Django / Gunicorn                                           │
       │  SecurityMiddleware → WhiteNoise → Session → Common → CSRF   │
       │  → Auth → TenantResolution → Messages → XFrameOptions        │
       │                                                              │
       │  apps.accounts   custom User (email login, Argon2)           │
       │  apps.tenants    Tenant / Domain / Membership, middleware    │
       │  apps.projects   work-management domain + DRF API v1         │
       │  apps.billing    Subscription / Invoice / LedgerEntry        │
       │  apps.core       shared mixins, throttles, PII-safe logging  │
       └──────┬──────────────────────┬──────────────────────┬─────────┘
              │                      │                      │
     ┌────────▼────────┐    ┌────────▼────────┐    ┌────────▼────────┐
     │  PostgreSQL 16  │    │  Redis           │    │  Celery workers │
     │  (TLS, row-level│    │  db0 cache       │    │  invoices,      │
     │  tenant FKs,    │    │  db1 broker      │    │  HMAC-signed    │
     │  constraints)   │    │  db2 results     │    │  webhooks       │
     └─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 4. Request lifecycle (tenant request)

1. `Host: acme.meridian.app` validated against `ALLOWED_HOSTS`
   (`.meridian.app`) — `DisallowedHost` on mismatch.
2. `TenantResolutionMiddleware` checks the Redis domain cache
   (`tenant:domain:<host>`, 300 s TTL, negative results cached) and falls back
   to `Domain` → active `Tenant` lookup. Unknown host → 404.
3. Tenant id bound to a `ContextVar` (async-safe, reset in `finally`);
   `request.tenant` set.
4. View/DRF layer: `IsTenantMember` confirms membership; role permission
   gates the method; the default manager scopes every query to the tenant.
5. Response; context unbound.

Public hosts (`meridian.app`, `www`) bypass tenant resolution and host the
marketing site, admin, and health endpoint.

## 5. Data model

```
accounts.User          email (citext-unique), password (Argon2), is_staff, is_active
tenants.Tenant         name, slug, is_active
tenants.Domain         tenant FK, hostname (unique, lowercase), is_primary
tenants.Membership     user FK ↔ tenant FK, role {OWNER|ADMIN|MEMBER|VIEWER}, unique(user, tenant)

projects.Project       tenant FK, name, key, owner FK(User), is_archived
projects.WorkItem      tenant FK, project FK, title, status, assignee FK, due_at

billing.Subscription   tenant FK, plan, status, period, seats
                       └─ partial unique: ONE active/trialing per tenant
billing.Invoice        tenant FK, subscription FK, number (unique per tenant),
                       total Decimal(18,4), status, idempotency_key (unique)
billing.LedgerEntry    tenant FK, invoice FK, direction {DEBIT|CREDIT},
                       amount Decimal > 0 (check constraint), append-only
```

Financial integrity rules:

- Money is `Decimal`, never float.
- `LedgerEntry` is **append-only**: `save()` on an existing row and
  `delete()` both raise.
- Invoice issuance runs in `transaction.atomic()` with
  `select_for_update()` on the subscription row; an `idempotency_key`
  makes Celery retries safe.

## 6. API boundaries

| Boundary | Path | Auth | Notes |
|----------|------|------|-------|
| Tenant API v1 | `https://<tenant>.meridian.app/api/v1/` | Session + CSRF | JSON only; browsable renderer disabled |
| Health | `/healthz/` | none | liveness only, no data |
| Admin | `https://meridian.app/<ADMIN_URL>` | staff session | path set per-deploy via env |

API conventions: explicit serializer fields (never `fields = "__all__"`),
cursorless page pagination, three throttle scopes
(`burst` 60/min, `sustained` 1000/day per user, `tenant` 10000/day).

## 7. Asynchronous architecture

- `billing.tasks.issue_invoice_task` — idempotent invoice generation
  (`acks_late`, bounded retries with backoff, JSON-only serialization).
- `billing.tasks.send_invoice_paid_webhook` — fired by a `post_save` signal
  when an invoice transitions to PAID; payload signed with a per-tenant HMAC
  secret; destination URL validated against SSRF (https-only, no private
  address literals).
- Workers never rely on ambient tenant state: every task receives an explicit
  `tenant_id` and enters `tenant_context()` itself.
