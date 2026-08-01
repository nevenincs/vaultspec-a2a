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

# Where the engine's a2a edge module lives inside the consuming project's tree.
_EDGE_MODULE = Path("engine/crates/vaultspec-api/src/routes/ops/a2a.rs")

# Env override first, then the conventional sibling checkouts. The worktree
# layout this project develops in keeps both repositories side by side.
_ENGINE_SOURCE_ENV = "VAULTSPEC_ENGINE_SOURCE"
_CONVENTIONAL_ROOTS = (
    Path("Y:/code/vaultspec-dashboard-worktrees/agent-panel"),
    Path("Y:/code/vaultspec-dashboard-worktrees/main"),
    Path("Y:/code/vaultspec-dashboard"),
)


def _edge_source() -> str:
    """Return the engine edge module's text, or skip naming what is missing."""
    override = os.environ.get(_ENGINE_SOURCE_ENV)
    roots = [Path(override)] if override else list(_CONVENTIONAL_ROOTS)
    for root in roots:
        candidate = root / _EDGE_MODULE
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    searched = ", ".join(str(root / _EDGE_MODULE) for root in roots)
    pytest.skip(
        "engine source not on disk, so the shared bounds cannot be compared; "
        f"set {_ENGINE_SOURCE_ENV} to a dashboard checkout root (searched: "
        f"{searched})"
    )


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
