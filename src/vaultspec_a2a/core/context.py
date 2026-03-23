"""Backwards-compat shim — canonical: vaultspec_a2a.context.token_budget."""

from vaultspec_a2a.context.token_budget import (
    compact_context as compact_context,
)
from vaultspec_a2a.context.token_budget import (
    estimate_tokens as estimate_tokens,
)
from vaultspec_a2a.context.token_budget import (
    prepare_handoff as prepare_handoff,
)
from vaultspec_a2a.context.token_budget import (
    should_compact as should_compact,
)

__all__ = [
    "compact_context",
    "estimate_tokens",
    "prepare_handoff",
    "should_compact",
]
