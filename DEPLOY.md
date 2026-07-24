# Deploying Meridian

Meridian is a stateful multi-service app: **web (Django) + Celery worker +
PostgreSQL + Redis**. It cannot run on static/serverless hosts (Vercel/Netlify)
— it needs a persistent process, a real database, and a broker. The repo ships
a [`render.yaml`](render.yaml) Blueprint that provisions all four on Render.

## One-click deploy (Render)

1. Sign in at <https://dashboard.render.com> (this is the step only you can do —
   it creates billable managed Postgres/Redis under your account).
2. **New → Blueprint** → connect `sidhvik17/meridian-saas` → **Apply**.
   Or use: `https://render.com/deploy?repo=https://github.com/sidhvik17/meridian-saas`
3. Render creates `meridian-web`, `meridian-worker`, `meridian-db`,
   `meridian-redis` and injects every secret from `render.yaml`
   (`DJANGO_SECRET_KEY` is generated; DB/Redis creds are wired automatically).
4. After the **first** deploy finishes, copy the web URL
   (`https://meridian-web-xxxx.onrender.com`) and set one env var on
   `meridian-web`:

   ```
   DJANGO_CSRF_TRUSTED_ORIGINS = https://meridian-web-xxxx.onrender.com
   ```

   Then **Manual Deploy → Clear build cache & deploy** once. (CSRF needs the
   full `https://host` form, which a Blueprint can't derive from the hostname
   alone.)

The `preDeployCommand` runs `migrate` + `seed_demo`, so demo data is loaded.
Demo login is printed by `seed_demo` (see `apps/core/management/commands/seed_demo.py`).

## What works on the default `.onrender.com` URL

- `/` marketing landing, `/admin/`, and login — these are **public** (no tenant).
- The health check `/healthz/`.

## Enabling full multi-tenancy (tenant subdomains)

Tenant portals resolve by **exact hostname** in the `Domain` table
(`acme.<your-domain>`), so `*.onrender.com` subdomains won't route. To demo
tenant isolation live:

1. Add a **custom domain** on `meridian-web` (e.g. `meridian.app`) plus a
   wildcard `*.meridian.app` (Render custom domains + wildcard CNAME).
2. Set `DJANGO_ALLOWED_HOSTS = meridian.app,.meridian.app` and
   `DJANGO_CSRF_TRUSTED_ORIGINS = https://*.meridian.app`.
3. Seed/create tenants whose `Domain` rows match `acme.meridian.app`, etc.

## Cost note

- `web`, `meridian-db`, `meridian-redis`: **free** tiers (free Postgres expires
  ~30 days).
- `meridian-worker`: Render background workers require a **paid** (`starter`)
  instance. The web/UI works without it; only async billing tasks need it. To
  run zero-cost, remove the `worker` service from `render.yaml` (billing tasks
  just won't process in the background).
