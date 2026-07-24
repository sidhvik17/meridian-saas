"""Server-rendered portal forms."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django import forms

from apps.accounts.models import User
from apps.projects.models import Project, WorkItem
from apps.tenants.models import Membership, Tenant


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "key", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class WorkItemForm(forms.ModelForm):
    class Meta:
        model = WorkItem
        fields = ["title", "status", "assignee", "due_at"]
        widgets = {
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args: Any, tenant: Tenant, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Assignee choices restricted to active members of THIS tenant —
        # the form can never reference users from another organisation.
        self.fields["assignee"].queryset = User.objects.filter(  # type: ignore[attr-defined]
            memberships__tenant=tenant, memberships__is_active=True
        ).distinct()


class AddMemberForm(forms.Form):
    """Invite/create a user and attach them to the current tenant."""

    email = forms.EmailField()
    role = forms.ChoiceField(choices=Membership.Role.choices, initial=Membership.Role.MEMBER)
    password = forms.CharField(
        min_length=12,
        widget=forms.PasswordInput(render_value=True),
        help_text="Only used if the user does not exist yet (min 12 chars).",
    )


class InvoiceLineForm(forms.Form):
    description = forms.CharField(max_length=200)
    amount = forms.DecimalField(
        min_value=Decimal("0.01"), max_digits=18, decimal_places=2
    )
