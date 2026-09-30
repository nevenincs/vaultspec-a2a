"""The degradation vocabulary offers only reasons a reader can still send.

A member with no producer is not harmless. A client branches on the token, so
one nothing emits is a branch that never runs and a failure mode the reader
appears to have and does not; and anyone reading the vocabulary to learn what
can go wrong learns something untrue. The sweep here is over the real package
source, because the hazard is a reader removed in a module nobody reopened.
"""

from __future__ import annotations

from pathlib import Path

from ..enums import DegradedReason

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]

#: The prefix naming the checkpoint-history read. Its reasons went from three
#: to one when history depth started coming off the checkpoint tuple the
#: caller already holds, which removed the separate read that could time out
#: or find the store unreachable.
_HISTORY_PREFIX = "checkpoint_history_"


def _production_sources() -> list[str]:
    """Every shipped module's text, minus the enumerations that declare names."""
    return [
        source.read_text(encoding="utf-8")
        for source in _PACKAGE_ROOT.rglob("*.py")
        if "tests" not in source.parts and source.name != "enums.py"
    ]


def test_every_checkpoint_history_degradation_has_a_producer() -> None:
    """Each history reason is one some reader can actually report."""
    declared = {
        member.value
        for member in DegradedReason
        if member.value.startswith(_HISTORY_PREFIX)
    }
    assert declared, "the history reason family is empty, so this proves nothing"

    sources = _production_sources()
    orphaned = sorted(
        reason
        for reason in declared
        if not any(f'"{reason}"' in source for source in sources)
    )

    assert not orphaned, (
        "these degradation reasons are declared but nothing in the package "
        f"reports them, so no client can ever receive one: {orphaned}"
    )
