"""Owned runtime ports and compilation state for graph lifecycle management."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio

    from ..database.checkpoints import Checkpointer
    from ..providers.factory import ProviderFactory
    from ..streaming.aggregator import EventAggregator
    from .catalog_store import RunCatalogStore
    from .graph_lifecycle import GraphCacheKey, RegisteredCompiledGraph
    from .ipc import WorkerBridge
    from .token_store import RunTokenStore


@dataclass(frozen=True, slots=True)
class GraphLifecyclePorts:
    """Services that a graph compilation and run share."""

    checkpointer: Checkpointer
    bridge: WorkerBridge
    aggregator: EventAggregator
    token_store: RunTokenStore
    catalog_store: RunCatalogStore
    provider_factory: ProviderFactory


@dataclass(slots=True)
class GraphLifecycleState:
    """Cache entries, thread bindings, and single-flight lock ownership."""

    graph_cache: OrderedDict[GraphCacheKey, RegisteredCompiledGraph] = field(
        default_factory=OrderedDict
    )
    thread_to_cache_key: dict[str, GraphCacheKey] = field(default_factory=dict)
    thread_compilation_digests: dict[str, tuple[str, str]] = field(default_factory=dict)
    thread_compile_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    thread_compile_lock_users: dict[str, int] = field(default_factory=dict)
    cache_key_compile_locks: dict[GraphCacheKey, asyncio.Lock] = field(
        default_factory=dict
    )
    cache_key_compile_lock_users: dict[GraphCacheKey, int] = field(default_factory=dict)
