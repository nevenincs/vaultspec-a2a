"""Domain configuration — pure behavioral knobs with zero infrastructure coupling.

These fields govern core logic (debounce windows, buffer sizes, token budgets,
recursion limits) and carry no dependency on ports, hosts, URLs, API keys, or
filesystem paths.  ``DomainConfig`` is the single source of truth consumed by
Layer 1 modules (thread/, context/, graph/, streaming/).
"""

from pydantic import BaseModel, Field


class DomainConfig(BaseModel):
    """Behavioural knobs consumed by Layer 1 (domain) modules."""

    # -- Event aggregator debounce / buffer (D-20) ---------------------------

    tool_call_debounce_seconds: float = Field(
        default=0.100,
        description="Aggregator: debounce window for ToolCallUpdateEvents (seconds).",
    )
    plan_update_debounce_seconds: float = Field(
        default=0.250,
        description="Aggregator: debounce window for PlanUpdateEvents (seconds).",
    )
    chunk_flush_interval_seconds: float = Field(
        default=0.050,
        description="Aggregator: interval between streaming chunk flushes (seconds).",
    )
    debounce_map_max_entries: int = Field(
        default=1000,
        description=(
            "Aggregator: maximum debounce-map entries before oldest are evicted."
        ),
    )
    chunk_buffer_max_bytes: int = Field(
        default=4096,
        description=(
            "Aggregator: maximum bytes buffered per streaming chunk before flush."
        ),
    )
    tool_arg_truncate_len: int = Field(
        default=1000,
        description=(
            "Aggregator: maximum length of tool argument strings before truncation."
        ),
    )
    event_queue_maxsize: int = Field(
        default=512,
        description="Aggregator: asyncio queue depth for outgoing events.",
    )
    aget_state_timeout_seconds: float = Field(
        default=10.0,
        description="Aggregator: timeout (seconds) for checkpointer aget_state calls.",
    )

    # -- Context window sizing (D-21) ----------------------------------------

    context_limit_tokens: int = Field(
        default=120_000,
        description="Estimated token budget for the context window.",
    )
    chars_per_token: int = Field(
        default=4,
        description=(
            "Characters-per-token approximation used for context size estimates."
        ),
    )

    # -- Workspace / context reference caps (D-22) ----------------------------

    anchor_path_cap: int = Field(
        default=10,
        description="Maximum anchor paths returned by the workspace anchoring module.",
    )
    max_context_refs: int = Field(
        default=50,
        description="Maximum context references included in a single graph invocation.",
    )
    vault_index_cap: int = Field(
        default=50,
        description="Maximum vault index entries surfaced to the agent per turn.",
    )
    mount_token_ceiling: int = Field(
        default=20_000,
        description="Maximum tokens consumed by mounted documents per turn.",
    )
    min_remaining_tokens_for_mount: int = Field(
        default=100,
        description=(
            "Minimum remaining token budget required before mounting any document."
        ),
    )
    task_queue_pending_horizon: int = Field(
        default=2,
        description=(
            "Number of upcoming task-queue entries to include in the agent prompt."
        ),
    )

    # -- LangGraph execution (D-16) ------------------------------------------

    graph_recursion_limit: int = Field(
        default=100,
        description="LangGraph recursion limit passed to every graph invocation.",
    )

    # -- Worker executor (D-18) ----------------------------------------------

    max_cached_graphs: int = Field(
        default=32,
        description=(
            "Maximum compiled LangGraph objects held in the executor LRU cache."
        ),
    )
    max_concurrent_threads: int = Field(
        default=5,
        description="Max concurrent graph executions per worker (WPA-001).",
    )


__all__ = ["DomainConfig"]
