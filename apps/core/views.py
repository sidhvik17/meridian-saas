"""Operational endpoints."""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health_check(request: HttpRequest) -> JsonResponse:
    """Liveness probe. Intentionally returns no version, hostname, or
    dependency details — fingerprinting fodder stays out of public output."""
    return JsonResponse({"status": "ok"})
