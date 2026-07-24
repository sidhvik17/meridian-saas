"""Tenant-isolation regression tests.

These are the security-critical tests: if any of them fails, cross-tenant
data exposure is possible and the build must not ship.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.projects.models import Project
from apps.tenants.context import TenantContextError, tenant_context
from apps.tenants.models import Domain, Membership, Tenant

User = get_user_model()


def _make_tenant(slug: str) -> Tenant:
    tenant = Tenant.objects.create(name=slug.title(), slug=slug)
    Domain.objects.create(tenant=tenant, hostname=f"{slug}.localtest.me", is_primary=True)
    return tenant


class TenantScopingTests(TestCase):
    """The fail-closed manager must make cross-tenant reads impossible."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.acme = _make_tenant("acme")
        cls.globex = _make_tenant("globex")
        cls.user = User.objects.create_user("owner@example.com", "x-strong-passw0rd-x")
        for tenant in (cls.acme, cls.globex):
            Membership.objects.create(
                user=cls.user, tenant=tenant, role=Membership.Role.OWNER
            )
            with tenant_context(tenant.pk):
                Project.objects.create(
                    name=f"{tenant.slug} project", key="CORE", owner=cls.user
                )

    def test_queries_without_bound_tenant_raise(self) -> None:
        with self.assertRaises(TenantContextError):
            list(Project.objects.all())

    def test_queries_are_scoped_to_bound_tenant(self) -> None:
        with tenant_context(self.acme.pk):
            projects = list(Project.objects.all())
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].tenant_id, self.acme.pk)

    def test_pk_lookup_cannot_cross_tenants(self) -> None:
        """IDOR guard: knowing another tenant's object id must not help."""
        with tenant_context(self.globex.pk):
            foreign_pk = Project.objects.get().pk
        with tenant_context(self.acme.pk):
            with self.assertRaises(Project.DoesNotExist):
                Project.objects.get(pk=foreign_pk)

    def test_save_without_context_raises(self) -> None:
        with self.assertRaises(TenantContextError):
            Project(name="orphan", key="ORPH", owner=self.user).save()

    def test_context_resets_after_block(self) -> None:
        with tenant_context(self.acme.pk):
            pass
        with self.assertRaises(TenantContextError):
            list(Project.objects.all())


class TenantMiddlewareTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.acme = _make_tenant("acme")

    def test_unknown_host_returns_404(self) -> None:
        response = self.client.get("/healthz/", HTTP_HOST="ghost.localtest.me")
        # /healthz/ is exempt; a tenant API path on an unknown host must 404.
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/api/v1/projects/", HTTP_HOST="ghost.localtest.me")
        self.assertEqual(response.status_code, 404)

    def test_known_host_resolves_tenant(self) -> None:
        response = self.client.get("/api/v1/projects/", HTTP_HOST="acme.localtest.me")
        # Unauthenticated: DRF returns 403 (session auth) — not 404, proving
        # the tenant resolved and the request reached the permission layer.
        self.assertIn(response.status_code, (401, 403))
