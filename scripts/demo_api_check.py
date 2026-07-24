"""End-to-end smoke check against a running demo server.

Usage (server must be running with config.settings.demo and seed_demo done):

    .venv/Scripts/python scripts/demo_api_check.py

Logs in via the session login form (real CSRF dance), then calls the
tenant-scoped API as an authenticated OWNER member.
"""
from __future__ import annotations

import re
import sys

import httpx

BASE = "http://127.0.0.1:8000"
TENANT_HOST = "acme.localtest.me"
EMAIL = "demo@meridian.dev"
# Local demo fixture only — never a production credential.
PASSWORD = "demo-Passw0rd-2026"  # noqa: S105 # nosec B105


def main() -> int:
    client = httpx.Client(base_url=BASE, headers={"Host": TENANT_HOST}, timeout=10)

    login_page = client.get("/admin/login/")
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login_page.text)
    if match is None:
        print("FAIL: no CSRF token on login page")
        return 1

    login = client.post(
        "/admin/login/",
        data={
            "username": EMAIL,
            "password": PASSWORD,
            "csrfmiddlewaretoken": match.group(1),
            "next": "/admin/",
        },
    )
    if login.status_code != 302:
        print(f"FAIL: login returned {login.status_code}")
        return 1
    print("login: OK (302)")

    for path in ("/api/v1/projects/", "/api/v1/work-items/"):
        response = client.get(path)
        print(f"GET {path} -> {response.status_code}")
        print(f"  {response.text[:200]}")
        if response.status_code != 200:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
