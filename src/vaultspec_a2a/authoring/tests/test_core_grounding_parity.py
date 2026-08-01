"""The grounding vocabulary this runtime enforces is vaultspec-core's, not a copy.

Core owns the framework's document dependency graph and checks it itself, in
``vaultcore/checks/references.py``. This runtime enforces the same rule at a
different moment: core validates a vault that already exists, while the submitter
refuses before a document is written, so a record core would reject never lands.
Same rule, two enforcement points - which is legitimate, and is exactly why the
VOCABULARY must not drift. A type core sanctions but this side omits becomes a
document the framework accepts and the runtime serving it refuses.

Core keeps the list as a function-local tuple with no importable name, so binding
to it directly is not available; this reads its source instead and asserts the
values match. That is a weaker coupling than an import and it is stated as such -
if core ever exports the vocabulary, this should become an import and this module
should shrink to nothing.

The plan rule is deliberately NOT asserted equal. Core requires the ADR and only
warns about research; the submitter requires both, by owner ruling, because a
warning raised after a plan exists is a refusal worth making before it lands.
That divergence is a decision, so the test below pins the part that must match
and leaves the part that must not.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ..submitter import _CORE_ADR_GROUNDING

_CHECKS_MODULE = Path("vaultspec_core") / "vaultcore" / "checks" / "references.py"


def _core_references_source() -> str:
    """Return core's reference-check source, or skip naming what is missing."""
    import vaultspec_core

    package_root = Path(vaultspec_core.__file__).resolve().parent.parent
    candidate = package_root / _CHECKS_MODULE
    if not candidate.is_file():
        pytest.skip(
            "vaultspec-core's reference checks are not readable at "
            f"{_CHECKS_MODULE.as_posix()}; the installed layout changed and this "
            "parity check needs repointing rather than deleting"
        )
    return candidate.read_text(encoding="utf-8")


def test_adr_grounding_vocabulary_matches_core() -> None:
    """Red when core widens or narrows what may ground an ADR and we do not follow.

    The failure this prevents is asymmetric and quiet: omitting a type core
    sanctions refuses a correctly grounded document at submit time, and the
    author sees a runtime refusal for a record the framework itself would pass.
    """
    source = _core_references_source()

    match = re.search(r"grounding_types\s*=\s*\(([^)]*)\)", source)
    assert match is not None, (
        "core no longer declares its ADR grounding types as a tuple literal named "
        "'grounding_types'; this reader needs updating to wherever the vocabulary "
        "moved - do not drop the assertion"
    )
    core_types = tuple(
        literal.strip().strip("\"'")
        for literal in match.group(1).split(",")
        if literal.strip()
    )

    assert set(core_types) == set(_CORE_ADR_GROUNDING), (
        f"ADR grounding vocabulary drift: core sanctions {sorted(core_types)}, "
        f"this runtime enforces {sorted(_CORE_ADR_GROUNDING)}"
    )


def test_core_still_requires_an_adr_for_a_plan() -> None:
    """The half we match: core treats a plan without an ADR as an error.

    If core ever downgrades this to a warning, our hard refusal stops being
    "stricter about the same rule" and becomes our own invention - which is a
    decision to retake deliberately, not to discover from a passing suite.
    """
    source = _core_references_source()
    plan_check = source.split("def _check_plan_grounding", 1)[-1]

    adr_severity = re.search(
        r"Plan has no references to ADR documents.*?Severity\.(\w+)",
        plan_check,
        re.DOTALL,
    )
    assert adr_severity is not None, (
        "core's plan check no longer raises a diagnostic naming a missing ADR"
    )
    assert adr_severity.group(1) == "ERROR", (
        "core downgraded 'plan without an ADR' from ERROR to "
        f"{adr_severity.group(1)}; our hard refusal is no longer a stricter "
        "reading of core's rule and needs re-deciding, not re-asserting"
    )

    research_severity = re.search(
        r"Plan has no references to research documents.*?Severity\.(\w+)",
        plan_check,
        re.DOTALL,
    )
    assert research_severity is not None, (
        "core's plan check no longer mentions research"
    )
    assert research_severity.group(1) == "WARNING", (
        "core changed the research diagnostic's severity; the submitter's stricter "
        "stance was chosen against a WARNING, so revisit it against "
        f"{research_severity.group(1)}"
    )
