from __future__ import annotations

from django.contrib import admin

from apps.tenants.models import Domain, Membership, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "is_active", "created_at")
    search_fields = ("slug", "name")
    list_filter = ("is_active",)


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("hostname", "tenant", "is_primary")
    search_fields = ("hostname",)
    list_select_related = ("tenant",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "role", "is_active")
    list_filter = ("role", "is_active")
    list_select_related = ("user", "tenant")
