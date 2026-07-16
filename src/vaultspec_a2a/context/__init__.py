"""Prompt enrichment pipeline: metadata, preamble, anchoring, rules, and token budget.

This is a Layer 1 module providing context injection and management
for orchestration threads.
"""

from .anchoring import build_anchoring_context as build_anchoring_context
from .harness import DEFAULT_REQUIRED_TEMPLATES as DEFAULT_REQUIRED_TEMPLATES
from .harness import HarnessReadiness as HarnessReadiness
from .harness import verify_harness as verify_harness
from .metadata import ContextRef as ContextRef
from .metadata import ThreadMetadata as ThreadMetadata
from .metadata import discover_context_refs as discover_context_refs
from .metadata import generate_nickname as generate_nickname
from .preamble import build_context_preamble as build_context_preamble
from .rules import RuleManager as RuleManager
from .stage import PHASE_ORDER as PHASE_ORDER
from .stage import infer_phase_from_vault_index as infer_phase_from_vault_index
from .token_budget import compact_context as compact_context
from .token_budget import estimate_tokens as estimate_tokens
from .token_budget import prepare_handoff as prepare_handoff
from .token_budget import should_compact as should_compact

__all__ = [
    "DEFAULT_REQUIRED_TEMPLATES",
    "PHASE_ORDER",
    "ContextRef",
    "HarnessReadiness",
    "RuleManager",
    "ThreadMetadata",
    "build_anchoring_context",
    "build_context_preamble",
    "compact_context",
    "discover_context_refs",
    "estimate_tokens",
    "generate_nickname",
    "infer_phase_from_vault_index",
    "prepare_handoff",
    "should_compact",
    "verify_harness",
]
