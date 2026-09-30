"""The degradation vocabulary offers only reasons a reader can still send.

A member with no producer is not harmless. A client branches on the token, so
one nothing emits is a branch that never runs and a failure mode the reader
appears to have and does not; and anyone reading the vocabulary to learn what
can go wrong learns something untrue. The sweep here is over the real package
source, because the hazard is a reader removed in a module nobody reopened.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..enums import DegradedReason

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _production_sources() -> list[str]:
    """Every shipped module's text, minus the enumerations that declare names."""
    return [
        source.read_text(encoding="utf-8")
        for source in _PACKAGE_ROOT.rglob("*.py")
        if "tests" not in source.parts and source.name != "enums.py"
    ]


#: A reason reaches a client as a member, or as a literal handed to a
#: snapshot's degradation list. A bare string elsewhere is not a producer:
#: ``"unknown"`` means something different in every vocabulary that uses it.
_APPENDED = re.compile(r'degraded_reasons\.append\(\s*"([a-z_]+)"\s*\)')
_CONSTRUCTED = re.compile(r"degraded_reasons=\[([^\]]*)\]")
_QUOTED = re.compile(r'"([a-z_]+)"')


def _reported_literals(sources: list[str]) -> set[str]:
    """Every literal some shipped module hands to a degradation list."""
    literals: set[str] = set()
    for source in sources:
        literals.update(_APPENDED.findall(source))
        for listed in _CONSTRUCTED.findall(source):
            literals.update(_QUOTED.findall(listed))
    return literals


def test_every_degradation_reason_has_a_producer() -> None:
    """Each declared reason is one some reader can actually report."""
    sources = _production_sources()
    literals = _reported_literals(sources)
    orphaned = sorted(
        member.value
        for member in DegradedReason
        if member.value not in literals
        and not any(f"DegradedReason.{member.name}" in source for source in sources)
    )
    assert not orphaned, (
        "these degradation reasons are declared but nothing in the package "
        f"reports them, so no client can ever receive one: {orphaned}"
    )
