"""Each concept this project rehomed must still have exactly one declaration.

A deduplication pass fixes the tree it ran against; it does nothing about the
next writer. This suite is the standing half of that work, and it exists because
the sweep that produced these homes twice caught a NEW duplicate created while
the sweep itself was running - a lane needing a concept reached for the nearest
shape rather than the canonical home. Both were found by a human-driven audit
that will not be repeated on every change, so the invariant is asserted here
instead.

Each case pins a concept, not a spelling. The count is the assertion and the
message names the home, so a failure tells the next writer where the answer
already lives rather than only that they broke something. A case is worth adding
here when a concept was consolidated AND a second declaration would be silently
wrong rather than loudly broken - a duplicate that fails a type check does not
need a test.

Scanning source text is deliberate. These are DECLARATION-site invariants, and a
declaration can be added without ever being imported by the code under test, so
importing the modules and inspecting them would miss exactly the case this
guards: a fresh copy nobody has wired up yet.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SOURCE_ROOT = Path(__file__).resolve().parents[1]


def _declaring_modules(pattern: str) -> list[str]:
    """Return every module whose SOURCE declares *pattern*, sorted."""
    expression = re.compile(pattern)
    this_file = Path(__file__).resolve()
    found = [
        path.relative_to(_SOURCE_ROOT).as_posix()
        for path in sorted(_SOURCE_ROOT.rglob("*.py"))
        # This module carries every pattern as a literal, so it would count
        # itself as a declaring site for all of them.
        if path.resolve() != this_file
        and expression.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    return found


@pytest.mark.parametrize(
    ("concept", "pattern", "expected", "home", "why"),
    [
        (
            "reviewer verdict vocabulary",
            r'VERDICT_APPROVED = "approved"',
            1,
            "thread/enums.py",
            "It was declared identically in the authoring lifecycle and the "
            "graph's phase gate, agreeing only by upkeep. Neither could import "
            "the other, so it lives in a module that imports nothing but StrEnum "
            "and is therefore reachable from both without a cycle.",
        ),
        (
            "vault stage glob patterns",
            r"\.vault/research/\*\{tag\}\*\.md",
            0,
            "context/stage.py",
            "The six stages were declared three times - once as an order and "
            "twice as byte-identical pattern maps - and the two scans run for "
            "the SAME run. The patterns are now DERIVED from the order, so no "
            "literal should appear anywhere; a literal reappearing means someone "
            "restated the vocabulary instead of deriving it.",
        ),
        (
            "ACP option-id kind heuristic",
            r"def _map_acp_option_kind",
            1,
            "streaming/types.py, private on purpose",
            "While it was public a second consumer chose it over the resolver "
            "and classified a declared denial as an approval. It is the "
            "resolver's last resort, not a peer that can be selected instead.",
        ),
        (
            "lenient JSON narrowers",
            r"def lenient_json_object\(",
            1,
            "providers/_json_contract.py",
            "Two provider modules each declared their own. They sit beside the "
            "RAISING trio deliberately: those signal a broken internal "
            "invariant, these degrade untrusted provider output, and a caller "
            "reaching for the wrong posture gets a crash on ordinary noise or "
            "silence where an invariant should have shouted.",
        ),
        (
            "process-tree kill escalation",
            r'"taskkill",',
            1,
            "utils/process.py",
            "The Windows escalation was implemented twice, once sync and once "
            "async, with both copies independently choosing the same two "
            "timeout budgets. A kill escalation is the last thing that should "
            "have two answers. Matched on the QUOTED argument so that prose "
            "describing the escalation does not count as implementing it.",
        ),
    ],
)
def test_a_rehomed_concept_still_has_one_declaration(
    concept: str,
    pattern: str,
    expected: int,
    home: str,
    why: str,
) -> None:
    """A concept consolidated into one home must not regrow a second."""
    declaring = _declaring_modules(pattern)
    assert len(declaring) == expected, (
        f"{concept} should be declared in exactly {expected} place(s) "
        f"({home}), but source-level declarations were found in {declaring}.\n\n"
        f"{why}\n\n"
        "If this is a deliberate new home, move the assertion with it. If it is "
        "a second declaration, consume the existing one instead."
    )
