"""Execution-context tenant binding.

A ``contextvars.ContextVar`` carries the active tenant id through the request
(or Celery task). Unlike thread-locals, ContextVars are safe under both
threaded WSGI and async ASGI execution.

The ORM layer (``TenantAwareManager``) treats an unbound context as an error,
so every entry point — HTTP middleware, Celery tasks, management commands —
must bind a tenant explicitly before touching tenant-owned data.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Final


class TenantContextError(RuntimeError):
    """Raised when tenant-owned data is accessed without a bound tenant."""


_current_tenant_id: Final[ContextVar[int | None]] = ContextVar(
    "current_tenant_id", default=None
)


def get_current_tenant_id() -> int | None:
    """Return the tenant id bound to the current execution context, if any."""
    return _current_tenant_id.get()


def bind_tenant(tenant_id: int) -> Token[int | None]:
    """Bind a tenant id; the caller MUST reset with :func:`unbind_tenant`."""
    return _current_tenant_id.set(tenant_id)


def unbind_tenant(token: Token[int | None]) -> None:
    """Restore the previous tenant binding."""
    _current_tenant_id.reset(token)


@contextmanager
def tenant_context(tenant_id: int) -> Iterator[None]:
    """Bind a tenant for the duration of a ``with`` block.

    The binding is always reset, even on exception, so a failure inside one
    tenant's work can never bleed scope into subsequent work on the same
    worker.
    """
    token = bind_tenant(tenant_id)
    try:
        yield
    finally:
        unbind_tenant(token)
