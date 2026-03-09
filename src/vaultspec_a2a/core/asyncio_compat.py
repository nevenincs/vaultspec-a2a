"""Asyncio compatibility helpers for backend-specific runtime constraints."""

from __future__ import annotations

import asyncio
import sys

from .config import settings


__all__ = ["configure_asyncio_runtime", "psycopg_compatible_loop"]


def configure_asyncio_runtime() -> None:
    """Apply backend-specific event loop policy fixes before startup."""
    if sys.platform != "win32":
        return

    if not (
        settings.resolved_database_backend == "postgres"
        or settings.resolved_checkpoint_backend == "postgres"
    ):
        return

    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is None:
        return
    if isinstance(asyncio.get_event_loop_policy(), selector_policy):
        return

    asyncio.set_event_loop_policy(selector_policy())


def psycopg_compatible_loop() -> asyncio.AbstractEventLoop:
    """Return a selector event loop instance for psycopg-compatible runs."""
    return asyncio.SelectorEventLoop()
