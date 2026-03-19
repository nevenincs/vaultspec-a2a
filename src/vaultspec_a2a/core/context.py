"""Context window management for LangGraph orchestration.

Provides token estimation, context compaction, and clean handoff
preparation as mandated by ADR-002 (context management) and ADR-008
(state serialization).
"""

from collections.abc import Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from .config import settings
from .state import TeamState

__all__ = [
    "compact_context",
    "estimate_tokens",
    "prepare_handoff",
    "should_compact",
]


def estimate_tokens(messages: Sequence[BaseMessage]) -> int:
    """Rough token count for a list of LangChain messages.

    Uses the widely-accepted ~4 chars/token heuristic. This is intentionally
    conservative — overestimating is safer than under-counting when deciding
    whether to compact.
    """
    total_chars = 0
    for msg in messages:
        content = msg.content
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            # Multi-part content (e.g. vision messages with text blocks)
            for part in content:
                if isinstance(part, str):
                    total_chars += len(part)
                elif isinstance(part, dict):
                    total_chars += len(part.get("text", ""))
    return total_chars // settings.chars_per_token


def should_compact(state: TeamState, max_tokens: int) -> bool:
    """Return True when the conversation is approaching the token ceiling.

    Triggers compaction at 80% of ``max_tokens`` to leave headroom for
    the next generation cycle.
    """
    current = estimate_tokens(state.get("messages", []))
    return current > int(max_tokens * 0.8)


def compact_context(state: TeamState, max_tokens: int) -> TeamState:
    """Return a copy of *state* with messages trimmed to fit *max_tokens*.

    Strategy (per ADR-002 — no sliding-window amnesia):
    1. Always preserve the first system message (core objective).
    2. Always preserve the last ``keep_recent`` messages (working context).
    3. Replace everything in between with a single summary message so the
       agent retains awareness that prior work occurred.

    The function returns a **new** ``TeamState`` dict — it never mutates
    the input.
    """
    messages: list[BaseMessage] = list(state.get("messages", []))
    if not messages:
        return dict(state)  # type: ignore[return-value]

    current_tokens = estimate_tokens(messages)
    if current_tokens <= max_tokens:
        return dict(state)  # type: ignore[return-value]

    # Separate system prefix from conversation body, then pin the first
    # HumanMessage (the original task) so it is never subject to budget
    # truncation.
    system_msgs: list[BaseMessage] = []
    body: list[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, SystemMessage) and not body:
            system_msgs.append(msg)
        else:
            body.append(msg)

    # Pin the first HumanMessage unconditionally — it is the user's original
    # task and must survive compaction regardless of budget pressure.
    pinned_human: BaseMessage | None = None
    remaining_body: list[BaseMessage] = []
    for msg in body:
        if pinned_human is None and isinstance(msg, HumanMessage):
            pinned_human = msg
        else:
            remaining_body.append(msg)
    # Work over the body without the pinned message so the budget calculation
    # does not accidentally count it twice.
    body = remaining_body

    # Keep enough recent messages to stay under budget after adding the
    # system prefix + pinned HumanMessage + a summary placeholder.  Clamp to
    # zero so that when system messages alone exceed max_tokens the budget
    # doesn't go negative and confuse the kept-message selection loop (H5 fix).
    summary_overhead = 50  # tokens for the inserted summary message
    system_tokens = estimate_tokens(system_msgs)
    pinned_tokens = estimate_tokens([pinned_human]) if pinned_human else 0
    budget = max(0, max_tokens - system_tokens - pinned_tokens - summary_overhead)

    kept: list[BaseMessage] = []
    kept_tokens = 0
    for msg in reversed(body):
        msg_tokens = estimate_tokens([msg])
        if kept_tokens + msg_tokens > budget:
            # Always preserve at least the most recent message so the agent
            # knows what was last asked of it, even if the budget is exhausted
            # by the system prefix alone.
            if not kept:
                kept.insert(0, msg)
            break
        kept.insert(0, msg)
        kept_tokens += msg_tokens

    # Build the compacted message list
    summary = HumanMessage(
        content=(
            "[Context compacted: earlier conversation history removed "
            "to stay within the token budget. The core objective and recent "
            "working context are preserved.]"
        )
    )
    pinned_list = [pinned_human] if pinned_human else []
    compacted_messages = [*system_msgs, *pinned_list, summary, *kept]

    new_state: TeamState = dict(state)  # type: ignore[assignment]
    new_state["messages"] = compacted_messages
    return new_state


def prepare_handoff(state: TeamState, target_agent: str) -> dict:
    """Prepare a lean state dict for handing off to *target_agent*.

    Per ADR-002, handoffs strip internal reasoning loops and pass only
    the compiled structural state.  The receiving agent gets:
    - ``thread_id``
    - ``current_plan``
    - ``artifacts``
    - ``active_agent`` (set to *target_agent*)
    - ``token_usage`` (cumulative, for bookkeeping)

    Conversation messages are **not** included — the receiving agent
    starts with a fresh context window seeded only by the structured
    state above.
    """
    return {
        "thread_id": state.get("thread_id", ""),
        "current_plan": list(state.get("current_plan", [])),
        "artifacts": list(state.get("artifacts", [])),
        "active_agent": target_agent,
        "token_usage": dict(state.get("token_usage", {})),
    }
