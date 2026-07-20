"""Define domain settings and the process-wide domain configuration.

:class:`vaultspec_a2a.domain_config.DomainConfig` represents resolved domain
configuration. :class:`vaultspec_a2a.domain_config.DomainSettingsConfig`
defines environment-based settings behavior.

Importing this module creates
:data:`vaultspec_a2a.domain_config.domain_config`, initializes configuration,
and reads environment-based settings.

The settings govern :mod:`vaultspec_a2a.context`, :mod:`vaultspec_a2a.graph`,
:mod:`vaultspec_a2a.streaming`, and :mod:`vaultspec_a2a.control.config`.
"""

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DomainConfig(BaseModel):
    """Behavioural knobs consumed by Layer 1 (domain) modules."""

    # -- Event aggregator debounce / buffer --------------------------------

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

    # -- Context window sizing -----------------------------------------------

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

    # -- Workspace / context reference caps ----------------------------------

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

    # -- LangGraph execution -------------------------------------------------

    graph_recursion_limit: int = Field(
        default=100,
        description="LangGraph recursion limit passed to every graph invocation.",
    )

    # -- Worker executor -----------------------------------------------------

    max_cached_graphs: int = Field(
        default=32,
        description=(
            "Maximum compiled LangGraph objects held in the executor LRU cache."
        ),
    )
    max_concurrent_threads: int = Field(
        default=5,
        description="Max concurrent graph executions per worker.",
    )
    admission_reservation_ttl_seconds: float = Field(
        default=120.0,
        description=(
            "Seconds a desktop run-admission prepare reservation is held before it "
            "expires and frees its bounded slot when no commit binds it."
        ),
    )


class DomainSettingsConfig(BaseSettings, DomainConfig):
    """Env-reading subclass of DomainConfig.

    Reads ``VAULTSPEC_``-prefixed environment variables and ``.env`` files so
    that Layer 1 consumers get production values without importing the full
    infrastructure ``Settings`` object from ``control.config``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="VAULTSPEC_",
        extra="ignore",
    )


# Module-level singleton — Layer 1 modules import this directly.
domain_config = DomainSettingsConfig()

__all__ = ["DomainConfig", "DomainSettingsConfig", "domain_config"]
