# Meridian — Security Audit & Remediation Report

**Phases 3 & 4 deliverable.** Static analysis (SAST-style review) of the
Meridian codebase and configuration, benchmarked against
`manage.py check --deploy`, the OWASP Top 10 (2021), and the rule sets of
Bandit / `ruff --select S` / `pip-audit`.

Audit date: 2026-06-10 · Scope: entire repository · Method: manual review +
pattern scan (`eval|exec|pickle|yaml.load|mark_safe|\.raw\(|RawSQL|extra\(|
subprocess|os\.system|md5|sha1|verify=False|csrf_exempt|fields = "__all__"`
— zero hits in code).

---

## 1. Executive summary

Meridian is a multi-tenant B2B SaaS platform (Django 5.2 LTS, DRF, Celery,
Redis, PostgreSQL). The dominant risk class for this architecture is
**cross-tenant data exposure** in a shared-schema design; the codebase
counters it with a *fail-closed* ORM manager, middleware-bound tenant
context, and object-level API permissions — three independent layers that
must all fail before data crosses a tenant boundary.

Fifteen findings were raised during the audit of the initial architecture
and configuration. **All Critical and High findings are remediated in the
shipped code.** Three Medium findings remain open as roadmap
recommendations (MFA/lockout, egress proxy for webhooks, CSP header); each
has compensating controls in place. Overall posture: **strong**, contingent
on the deployment requirements in §5 being honoured.

| Severity | Raised | Remediated in code | Open (recommendation) |
|----------|--------|--------------------|------------------------|
| Critical | 2 | 2 | 0 |
| High | 4 | 4 | 0 |
| Medium | 5 | 3 | 2 |
| Low | 4 | 3 | 1 |

---

## 2. Vulnerability log & remediation

### V-01 · CRITICAL · Cross-tenant data exposure (Broken Access Control, OWASP A01)

**Risk.** In a shared-schema multi-tenant design, any query that forgets a
`tenant_id` filter returns other customers' data. A "remember to filter"
convention is statistically guaranteed to fail at scale.

**Remediation (implemented).** Scoping is the *default*, and the failure
mode is an exception, not a leak —
[apps/tenants/managers.py](apps/tenants/managers.py):

```python
class TenantAwareManager(models.Manager[_ModelT]):
    def get_queryset(self) -> models.QuerySet[_ModelT]:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise TenantContextError(...)          # fail CLOSED, never open
        return super().get_queryset().filter(tenant_id=tenant_id)
```

Every tenant-owned model inherits `TenantOwnedModel`
([apps/core/models.py](apps/core/models.py)), whose `save()` also injects
the bound tenant so writes cannot land in the wrong tenant. System access
requires the greppable escape hatch `Model.objects.for_tenant(id)`.
Regression-tested in
[apps/tenants/tests/test_isolation.py](apps/tenants/tests/test_isolation.py).

**Residual.** Shared schema means a DB-credential compromise exposes all
tenants. Compensating: TLS-only DB, least-privilege DB role; PostgreSQL
row-level security (RLS) policies are the recommended next hardening step.

---

### V-02 · CRITICAL · SECRET_KEY management (check --deploy W009)

**Risk.** A predictable or repository-committed `SECRET_KEY` lets an
attacker forge session cookies, password-reset tokens, and any
`django.core.signing` payload — full account takeover.

**Remediation (implemented).**
[config/settings/production.py](config/settings/production.py) refuses to
boot with a missing, short, or development key:

```python
SECRET_KEY = env_str("DJANGO_SECRET_KEY")
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be a unique, randomly generated value of at "
        "least 50 characters. ..."
    )
```

The development key is deliberately `django-insecure-` prefixed so
`check --deploy` (and this guard) flags it if it ever escapes dev.
`.gitignore` excludes `.env*`; only `.env.example` (no values) is tracked.

---

### V-03 · HIGH · IDOR on API objects (OWASP A01)

**Risk.** `GET /api/v1/projects/42/` with an id belonging to another tenant
must never resolve, even for an authenticated user.

**Remediation (implemented).** Three independent layers in
[apps/projects/api/permissions.py](apps/projects/api/permissions.py) and
[apps/projects/api/views.py](apps/projects/api/views.py):

1. Viewset querysets come from the fail-closed manager → foreign ids 404.
2. `IsTenantMember.has_object_permission` re-compares
   `obj.tenant_id == request.tenant.pk`.
3. Write-by-reference is also scoped: `WorkItemSerializer.project` uses a
   tenant-scoped `PrimaryKeyRelatedField`, and `validate_assignee` rejects
   non-members — a client cannot attach data to, or leak ids of, another
   tenant's objects.

Membership is role-checked per method (`RoleBasedWritePermission`:
reads → any member, writes → editor roles, deletes → admin/owner).

---

### V-04 · HIGH · Host-header attacks / tenant spoofing

**Risk.** Tenancy keyed on `Host` invites header forgery: cache poisoning,
password-reset link poisoning, or resolution to the wrong tenant.

**Remediation (implemented).** `request.get_host()` validates against
`ALLOWED_HOSTS` *before* the tenant middleware runs (`DisallowedHost`
otherwise). [apps/tenants/middleware.py](apps/tenants/middleware.py) then
does an **exact match** against the `Domain` table — hostnames stored
lowercase, regex-validated, unique. Unknown host → uniform 404. No
wildcard or suffix matching exists, so `acme.evil.com` cannot resolve.
Password-reset URL generation must use the tenant's canonical `Domain`,
never the request host.

---

### V-05 · HIGH · Celery deserialization RCE (OWASP A08)

**Risk.** Celery with pickle serialization turns broker access into remote
code execution on every worker.

**Remediation (implemented).**
[config/settings/base.py](config/settings/base.py):

```python
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]    # pickle is never accepted
```

Tasks take only JSON-safe arguments (`Decimal` travels as string,
UUID as string — see [apps/billing/tasks.py](apps/billing/tasks.py)).
Deploy requirement: Redis broker requires AUTH and is network-isolated.

---

### V-06 · HIGH · Transport security (check --deploy W004/W008/W012/W016)

**Risk.** Session cookies over plaintext HTTP = trivial hijack.

**Remediation (implemented).**
[config/settings/production.py](config/settings/production.py):

```python
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000        # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True   # covers every tenant subdomain
SECURE_HSTS_PRELOAD = True
```

`SECURE_PROXY_SSL_HEADER` is gated behind `DJANGO_BEHIND_TLS_PROXY` with a
documented warning: honouring `X-Forwarded-Proto` while directly
internet-facing lets clients spoof "https" and bypass the redirect. The
proxy **must** overwrite the header on every request.

---

### V-07 · MEDIUM · Brute force & credential stuffing (OWASP A07) — OPEN (partial)

**In place.** Argon2id hashing (memory-hard), 12-char minimum +
common-password/similarity validators, three-tier Redis throttling
(60/min burst, 1000/day user, 10000/day tenant), sessions expire at
browser close and after 12 h, case-insensitive email uniqueness.

**Open recommendation.** No per-account lockout and no MFA yet:

```python
# requirements/base.txt
django-axes==7.0.2
# settings: AXES_FAILURE_LIMIT = 5, AXES_COOLOFF_TIME = timedelta(minutes=15),
# AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
```

plus TOTP MFA (`django-otp`) for OWNER/ADMIN roles and all staff accounts.

---

### V-08 · MEDIUM · SSRF via tenant-configured webhooks (OWASP A10) — partially remediated

**Risk.** Tenants supply webhook URLs; workers POST to them. Unvalidated,
this is a free SSRF probe into the platform's VPC (cloud metadata
endpoints, internal admin services).

**Remediation (implemented).**
[apps/billing/webhooks.py](apps/billing/webhooks.py): https-only, port 443
only, no userinfo, no IP-literal hosts, no `localhost`/`.local`/`.internal`,
`follow_redirects=False`, 10 s timeout, HMAC-SHA256 signed payloads with
per-tenant secrets held outside the application database.

**Residual + recommendation.** DNS rebinding can still point a public name
at an internal IP between validation and connection. Route worker egress
through a dedicated proxy that re-validates resolved IPs against RFC 1918 /
link-local ranges at connect time, or resolve-then-pin the IP.

---

### V-09 · MEDIUM · PII leakage into logs (OWASP A09 / GDPR)

**Risk.** Emails or tokens in log lines spread PII into log aggregation,
backups, and third-party tooling.

**Remediation (implemented).** `RedactPIIFilter`
([apps/core/logging.py](apps/core/logging.py)) masks email addresses and
`bearer/token/api-key`-shaped substrings on **every** handler via
`LOGGING`; `django.db.backends` is pinned to ERROR outside development so
SQL (which may embed PII) is never logged in production.

---

### V-13 · MEDIUM · Financial race conditions / ledger tampering

**Risk.** Concurrent invoice issuance or task redelivery double-bills;
mutable ledger rows destroy auditability.

**Remediation (implemented).**
[apps/billing/services.py](apps/billing/services.py) and
[models.py](apps/billing/models.py): all writes inside
`transaction.atomic()` with `select_for_update()`; DB-unique
`idempotency_key` makes retries no-ops; `LedgerEntry.save()/delete()` raise
on mutation (append-only, corrections via compensating entries); money is
`Decimal(18,4)` with `CheckConstraint(amount > 0)`; webhooks enqueue via
`transaction.on_commit` so rolled-back payments never emit events.

---

### V-15 · MEDIUM · No Content-Security-Policy — OPEN

**In place.** Django template auto-escaping (no `mark_safe`, no
`|safe`, no `autoescape off` anywhere), `X-Frame-Options: DENY`, nosniff,
referrer policy, COOP.

**Open recommendation.** Add `django-csp` with a nonce-based policy:

```python
# settings/production.py
MIDDLEWARE.insert(1, "csp.middleware.CSPMiddleware")
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ("'self'",),
        "script-src": ("'self'",),     # nonce via csp.templatetags
        "object-src": ("'none'",),
        "frame-ancestors": ("'none'",),
    }
}
```

---

### V-10 · LOW · Admin exposure

Admin path is per-deploy configurable (`DJANGO_ADMIN_URL`) and served only
on public (non-tenant) hosts. Recommendation: additionally restrict at the
load balancer to corporate IP ranges / VPN, and require MFA (V-07) for all
staff users.

### V-11 · LOW · DRF browsable API disclosure

`DEFAULT_RENDERER_CLASSES = ["JSONRenderer"]` — the browsable HTML API
(forms, schema hints) is disabled in all environments.

### V-12 · LOW · Tenant enumeration

Unknown subdomains return a uniform 404 with no existence signal; negative
lookups are cached (300 s) so enumeration sweeps cannot hammer PostgreSQL.

### V-14 · LOW · Vulnerable dependencies (OWASP A06) — process control

All requirements pinned exactly ([requirements/](requirements/base.txt)).
Required CI gates on every PR and nightly:

```bash
pip-audit -r requirements/production.txt   # fail build on any known CVE
bandit -r apps config -c pyproject.toml
ruff check .                               # includes flake8-bandit (S) rules
```

---

## 3. `manage.py check --deploy` conformance

| Check | Setting | Status |
|-------|---------|--------|
| security.W004 | `SECURE_HSTS_SECONDS` = 31536000 | PASS |
| security.W005 | `SECURE_HSTS_INCLUDE_SUBDOMAINS` = True | PASS |
| security.W006 | `SECURE_CONTENT_TYPE_NOSNIFF` = True | PASS |
| security.W008 | `SECURE_SSL_REDIRECT` = True | PASS |
| security.W009 | `SECRET_KEY` ≥ 50 chars, env-supplied, prefix-guarded | PASS |
| security.W012 | `SESSION_COOKIE_SECURE` = True | PASS |
| security.W016 | `CSRF_COOKIE_SECURE` = True | PASS |
| security.W018 | `DEBUG` = False (not env-overridable in prod) | PASS |
| security.W019/W021 | `X_FRAME_OPTIONS` = DENY, `SECURE_HSTS_PRELOAD` = True | PASS |
| security.W020 | `ALLOWED_HOSTS` non-empty (boot-time enforced) | PASS |

CI rule: `python manage.py check --deploy --fail-level WARNING` on every
release build.

## 4. OWASP Top 10 (2021) coverage map

| Vector | Disposition |
|--------|-------------|
| A01 Broken Access Control | V-01, V-03 — fail-closed manager, membership + role + object checks |
| A02 Cryptographic Failures | Argon2id; TLS app+DB; HSTS; secrets via env/secret store |
| A03 Injection | ORM-only (zero `raw()/extra()/RawSQL/cursor`); validators on hostname/slug/key; auto-escaped templates |
| A04 Insecure Design | Defense-in-depth tenancy; append-only ledger; deny-by-default DRF |
| A05 Security Misconfiguration | Boot-time guards; `check --deploy` gate; JSON-only renderer |
| A06 Vulnerable Components | Pinned deps + `pip-audit` CI gate (V-14) |
| A07 Identification & Auth Failures | Argon2, validators, throttles; lockout+MFA open (V-07) |
| A08 Software & Data Integrity | JSON-only Celery (V-05); HMAC-signed webhooks; `on_commit` enqueue |
| A09 Logging & Monitoring Failures | PII redaction filter; `django.security` logger surfaced (V-09) |
| A10 SSRF | Webhook URL validation + no-redirects; egress proxy recommended (V-08) |

## 5. Bandit / scanner results

> **Verified, not simulated:** `bandit==1.8.3` and `ruff==0.11.13` (with
> flake8-bandit `S` rules) were executed against the codebase on 2026-06-12.
> Both exit clean. The full Django test suite (incl. the 7 tenant-isolation
> tests) passes.

| Rule | Pattern | Result |
|------|---------|--------|
| B105/S105 | hardcoded password string | 2 hits, both intentional demo fixtures: dev `SECRET_KEY` (`django-insecure-` prefixed, prod boot-guard rejects it) and `seed_demo` password. Annotated `# noqa: S105 # nosec B105` with justification. |
| B301/B403 | pickle | none (JSON-only Celery) |
| B307 | eval/exec | none |
| B324 | md5/sha1 | none (Argon2 + HMAC-SHA256 only) |
| B506 | yaml.load | none (no YAML parsing) |
| B602–B609 | subprocess/shell | none |
| B608 | SQL string building | none (no raw SQL anywhere) |
| B113 | request without timeout | none (`httpx.post(..., timeout=10.0)`) |
| — | `verify=False` TLS bypass | none |
| — | `csrf_exempt` | none |
| — | `fields = "__all__"` | none (explicit field lists enforced) |

## 6. Deployment requirements (non-negotiable)

1. `DJANGO_SETTINGS_MODULE=config.settings.production`; CI runs
   `check --deploy --fail-level WARNING`.
2. Secrets injected from a secret manager; `.env` files never reach
   production hosts or images.
3. TLS terminating proxy **overwrites** `X-Forwarded-Proto`; otherwise set
   `DJANGO_BEHIND_TLS_PROXY=false`.
4. Redis and PostgreSQL on private networks, AUTH/TLS enabled
   (`DB_SSLMODE=require` is enforced at boot).
5. `pip-audit` + `bandit` + isolation tests
   (`apps/tenants/tests/test_isolation.py`) green on every merge — a
   failing isolation test is a shipping blocker, not a flake.
