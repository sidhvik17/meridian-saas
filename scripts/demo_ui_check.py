"""End-to-end UI smoke check: login + every portal page + write operations.

Usage (demo server running, seed_demo applied):

    .venv/Scripts/python scripts/demo_ui_check.py
"""
from __future__ import annotations

import re
import sys
import uuid

import httpx

BASE = "http://127.0.0.1:8000"
TENANT_HOST = "acme.localtest.me"
EMAIL = "demo@meridian.dev"
# Local demo fixture only — never a production credential.
PASSWORD = "demo-Passw0rd-2026"  # noqa: S105 # nosec B105


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    if match is None:
        raise AssertionError("no CSRF token in page")
    return match.group(1)


def main() -> int:
    client = httpx.Client(
        base_url=BASE, headers={"Host": TENANT_HOST}, timeout=10, follow_redirects=True
    )

    # Anonymous: tenant root must land on the login page.
    page = client.get("/")
    assert "Sign in" in page.text, "anon root did not reach login"
    print("anon / -> login page: OK")

    # Log in through the real form.
    login = client.post(
        "/accounts/login/",
        data={
            "username": EMAIL,
            "password": PASSWORD,
            "csrfmiddlewaretoken": csrf_from(page.text),
            "next": "/dashboard/",
        },
    )
    assert login.status_code == 200 and "Dashboard" in login.text, "login failed"
    print("login -> dashboard: OK")

    for path, marker in [
        ("/dashboard/", "Open work items"),
        ("/projects/", "New project"),
        ("/billing/", "Issue invoice"),
        ("/members/", "Add member"),
    ]:
        response = client.get(path)
        assert response.status_code == 200 and marker in response.text, f"{path} broken"
        print(f"GET {path} -> 200: OK")

    # Write op 1: add a member (unique per run).
    members = client.get("/members/")
    new_email = f"user-{uuid.uuid4().hex[:6]}@example.com"
    response = client.post(
        "/members/",
        data={
            "email": new_email,
            "role": "member",
            "password": "another-Strong-Pass-1",
            "csrfmiddlewaretoken": csrf_from(members.text),
        },
    )
    assert new_email in response.text, "member add failed"
    print(f"POST /members/ ({new_email}): OK")

    # Write op 2: create a project (key unique per run).
    projects = client.get("/projects/")
    key = f"X{uuid.uuid4().hex[:4].upper()}"
    response = client.post(
        "/projects/",
        data={
            "name": f"Demo project {key}",
            "key": key,
            "description": "Created by demo_ui_check",
            "csrfmiddlewaretoken": csrf_from(projects.text),
        },
    )
    assert response.status_code == 200 and key in response.text, "project create failed"
    print(f"POST /projects/ ({key}): OK")

    # Write op 3: add a work item to the new project.
    detail_url = response.url.path
    response = client.post(
        detail_url,
        data={
            "title": "Smoke-test item",
            "status": "backlog",
            "assignee": "",
            "due_at": "",
            "csrfmiddlewaretoken": csrf_from(response.text),
        },
    )
    assert "Smoke-test item" in response.text, "work item create failed"
    print(f"POST {detail_url} work item: OK")

    print("ALL UI CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
