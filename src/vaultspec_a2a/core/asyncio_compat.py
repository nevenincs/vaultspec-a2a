"""Asyncio compatibility helpers for backend-specific runtime constraints."""

from __future__ import annotations


__all__ = ["configure_asyncio_runtime"]


def configure_asyncio_runtime() -> None:
    """Keep the default runtime loop policy.

    Windows subprocess support requires the default Proactor event loop. The
    Postgres checkpointer's selector-only requirements are isolated behind the
    checkpointer factory instead of changing the loop policy for the whole
    gateway/worker process.
    """
