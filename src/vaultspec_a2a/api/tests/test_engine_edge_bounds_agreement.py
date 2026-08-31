"""The bounds both sides of the edge claim to share are actually the same number.

Two constants on the engine's a2a edge are documented as mirrors of constants
here, and the mirroring is load-bearing rather than cosmetic:

- the role ceiling, which the engine describes as "the sibling caps a
  prepared/preset role set at 64; the dashboard applies the same ceiling before
  minting so an authenticated but drifted response cannot create unbounded actors
  or credentials";
- the discovery heartbeat staleness threshold, which the engine describes as
  mirroring this side's value.

Their independence is deliberate and correct: the engine must bound what it
accepts from us without trusting a number we supply, so this is defence in depth
rather than duplication to collapse. What was missing is that "the same ceiling"
was asserted only in a comment. Nothing made the two numbers move together, and
nothing would have noticed them drifting apart.

Drift is not symmetrical, which is why this is worth a gate. If the engine's
ceiling falls below ours, a preset we accept produces a prepare response the
engine refuses - and the refusal lands before dispatch, so no graph runs and the
failure is invisible to every test that exercises one. If ours falls below the
engine's we merely become the stricter side, which is safe but silently narrows
what the product supports.

This reads the engine's Rust source rather than calling a running engine on
purpose: the constants are compile-time bounds, so the source IS the contract,
and a running engine would only report what one build happens to carry. When the
engine tree is not on disk the check skips with a pointer, because a bound we
cannot read is not a bound we can claim agreement with.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from ...authoring.discovery import HEARTBEAT_STALE_MS
from ...thread.actor_tokens import MAX_ROLES_PER_RUN
from ...thread.clarification import MAX_ANSWER_CHARS, MAX_REQUEST_ID_CHARS

# Where the engine's a2a edge module lives inside the consuming project's tree.
_EDGE_MODULE = Path("engine/crates/vaultspec-api/src/routes/ops/a2a.rs")

# The engine declares its clarification bounds in the shared product crate
# rather than on the edge module, and the edge only aliases them. Reading the
# declaration is the point: an alias would report agreement with whatever the
# declaration happens to say.
_CONTRACT_MODULE = Path("engine/crates/vaultspec-product/src/a2a_contract.rs")

# Env override first, then the conventional sibling checkouts. The worktree
# layout this project develops in keeps both repositories side by side.
_ENGINE_SOURCE_ENV = "VAULTSPEC_ENGINE_SOURCE"
_CONVENTIONAL_ROOTS = (
    Path("Y:/code/vaultspec-dashboard-worktrees/agent-panel"),
    Path("Y:/code/vaultspec-dashboard-worktrees/main"),
    Path("Y:/code/vaultspec-dashboard"),
)


def _engine_module_source(module: Path) -> str:
    """Return an engine module's text, or skip naming what is missing."""
    override = os.environ.get(_ENGINE_SOURCE_ENV)
    roots = [Path(override)] if override else list(_CONVENTIONAL_ROOTS)
    for root in roots:
        candidate = root / module
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    searched = ", ".join(str(root / module) for root in roots)
    pytest.skip(
        "engine source not on disk, so the shared bounds cannot be compared; "
        f"set {_ENGINE_SOURCE_ENV} to a dashboard checkout root (searched: "
        f"{searched})"
    )


def _edge_source() -> str:
    """Return the engine edge module's text, or skip naming what is missing."""
    return _engine_module_source(_EDGE_MODULE)


def _contract_source() -> str:
    """Return the engine's shared a2a contract module, or skip."""
    return _engine_module_source(_CONTRACT_MODULE)


def _engine_const(source: str, name: str) -> int:
    """Return the integer an engine `const NAME: type = value;` declares."""
    match = re.search(
        rf"const\s+{re.escape(name)}\s*:\s*\w+\s*=\s*([0-9_]+)\s*;", source
    )
    assert match is not None, (
        f"the engine edge module no longer declares {name!r} as an integer "
        "constant; this gate reads it by name, so a rename or a computed value "
        "needs this reader updated rather than the assertion dropped"
    )
    return int(match.group(1).replace("_", ""))


def test_role_ceiling_is_the_same_number_on_both_sides() -> None:
    """Red when either side changes the ceiling the other applies.

    The engine's own comment states it applies "the same ceiling" as this side.
    That sentence is the contract; this is the check that it stays true.
    """
    engine_max = _engine_const(_edge_source(), "MAX_A2A_REQUIRED_ROLES")

    assert engine_max == MAX_ROLES_PER_RUN, (
        f"role ceiling drift: engine MAX_A2A_REQUIRED_ROLES={engine_max}, "
        f"a2a MAX_ROLES_PER_RUN={MAX_ROLES_PER_RUN}. If the engine's is the "
        "lower one, a preset this side accepts yields a prepare response the "
        "engine refuses, before any dispatch - no graph runs and no test that "
        "exercises one can see it."
    )


def test_heartbeat_staleness_is_the_same_number_on_both_sides() -> None:
    """Red when the two sides disagree on when a discovery record is stale.

    A consumer with a shorter threshold treats a live service as crashed and
    refuses to attach; a longer one attaches to a service that has already gone.
    Both are silent, and both look like the other side's fault.
    """
    engine_stale_ms = _engine_const(_edge_source(), "A2A_HEARTBEAT_STALE_MS")

    assert engine_stale_ms == HEARTBEAT_STALE_MS, (
        f"heartbeat staleness drift: engine A2A_HEARTBEAT_STALE_MS="
        f"{engine_stale_ms}, a2a HEARTBEAT_STALE_MS={HEARTBEAT_STALE_MS}"
    )


def test_clarification_answer_cap_is_the_same_number_on_both_sides() -> None:
    """Red when the engine forwards an answer this side's wire model refuses.

    This one is not hypothetical: the engine carried 4096 against this side's
    2048 for the whole life of the clarification verb, and the dashboard mirrored
    the engine. A human could type 4096 characters into the questionnaire, the
    composer would accept and submit them, the engine would forward them, and
    a2a returned 422 after a full round trip - with nothing in the message to say
    which layer objected.

    Both sibling guards stayed green through it, and the reason is the point of
    this gate. The engine asserts its edge alias equals its contract constant,
    and the dashboard asserts its constant equals the engine's contract constant.
    Every check compares a copy against another copy of the SAME number, so a
    wrong number is unanimous. Only a comparison against a2a's own constant -
    this one - can see it.
    """
    engine_answer_chars = _engine_const(
        _contract_source(), "A2A_MAX_CLARIFICATION_ANSWER_CHARS"
    )

    assert engine_answer_chars == MAX_ANSWER_CHARS, (
        f"clarification answer cap drift: engine "
        f"A2A_MAX_CLARIFICATION_ANSWER_CHARS={engine_answer_chars}, a2a "
        f"MAX_ANSWER_CHARS={MAX_ANSWER_CHARS}. A wider engine forwards an answer "
        "this side refuses at 422 after a round trip; a narrower one refuses an "
        "answer this side would have taken. Both are silent at the layer that "
        "caused them."
    )


def test_clarification_request_id_ceiling_is_not_below_what_a2a_mints() -> None:
    """Red when the engine would refuse a request id this side can mint.

    Deliberately an inequality, not an equality, because the two sides are not
    making the same claim about this number. a2a's is a MINTING ceiling: the
    respond route declares no bound on its ``request_id`` path parameter at all,
    so nothing here refuses a long one. The engine's is an ACCEPTANCE bound on a
    value it forwards.

    That makes the drift one-directional. An engine ceiling below this side's
    minting ceiling refuses a handle a2a issued, and the run stays parked with no
    way to answer it through the browser edge - the questionnaire is displayed
    and unanswerable. An engine ceiling above it costs nothing, because a2a
    resolves the id against its own parked checkpoint and refuses an unknown one
    on its own authority. So this asserts the safe direction rather than equality,
    and a future widening on either side stays green.
    """
    engine_request_id_chars = _engine_const(
        _contract_source(), "A2A_MAX_CLARIFICATION_REQUEST_ID_CHARS"
    )

    assert engine_request_id_chars >= MAX_REQUEST_ID_CHARS, (
        f"clarification request-id ceiling too low: engine "
        f"A2A_MAX_CLARIFICATION_REQUEST_ID_CHARS={engine_request_id_chars}, a2a "
        f"mints up to MAX_REQUEST_ID_CHARS={MAX_REQUEST_ID_CHARS}. The engine "
        "would refuse a handle this side issued, leaving the run parked on a "
        "question that cannot be answered through the edge."
    )


def _engine_str_slice(source: str, name: str) -> tuple[str, ...]:
    """Return the string literals an engine `const NAME: &[&str] = &[...];` lists.

    Order is preserved rather than sorted away: the two sides are one enumerated
    vocabulary, and a reader comparing them should be comparing the declaration,
    not a normalization of it.
    """
    match = re.search(
        rf"const\s+{re.escape(name)}\s*:\s*&\[&str\]\s*=\s*&\[(.*?)\];",
        source,
        re.DOTALL,
    )
    assert match is not None, (
        f"the engine contract module no longer declares {name!r} as a string "
        "slice; this gate reads it by name, so a rename or a computed value "
        "needs this reader updated rather than the assertion dropped"
    )
    return tuple(re.findall(r'"([^"]*)"', match.group(1)))


def test_provider_condition_vocabulary_is_the_same_set_on_both_sides() -> None:
    """Red when either side names a provider condition the other does not.

    This gate exists because the coupling is asymmetric and silent in the
    direction that costs the most. The engine validates an incoming condition
    against its own copy of the vocabulary and REFUSES a value it does not
    recognise, at the write boundary. So the day this side emits a new member
    without the engine having been taught it, the engine does not lose one
    field - it refuses to settle that run at all. The remedy is a release
    ordering nothing else enforces: teach the engine first.

    The reverse drift is harmless but worth catching too, since a member the
    engine accepts and this side never emits is a remediation affordance no
    user can ever reach, and it will look implemented.

    Read from the engine's source rather than from a running engine for the
    same reason as the bounds above: the declaration is the contract.
    """
    from ...providers.conditions import ProviderCondition

    engine_members = _engine_str_slice(_contract_source(), "A2A_PROVIDER_CONDITIONS")
    a2a_members = tuple(member.value for member in ProviderCondition)

    assert engine_members == a2a_members, (
        f"provider condition vocabulary drift: engine A2A_PROVIDER_CONDITIONS="
        f"{list(engine_members)}, a2a ProviderCondition={list(a2a_members)}. A "
        "member this side emits that the engine does not name is refused at the "
        "engine's write boundary, which loses the whole run's settlement rather "
        "than one field, so the engine has to learn a new member first."
    )
