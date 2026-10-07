"""Keyword options of ``GraphLifecycleManager`` beyond its three collaborators."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from .catalog_store import RunCatalogStore
    from .token_store import RunTokenStore

__all__ = ["GraphLifecycleOptions"]


class _GraphLifecycleRequired(TypedDict):
    token_store: RunTokenStore
    catalog_store: RunCatalogStore


class GraphLifecycleOptions(_GraphLifecycleRequired, total=False):
    checkpoint_read_timeout_seconds: float | None
