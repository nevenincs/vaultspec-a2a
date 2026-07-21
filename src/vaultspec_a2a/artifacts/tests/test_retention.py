"""The declaration must reject what it cannot act on.

The whole value of declaring retention is that a reviewer and a reaper can both
enumerate what exists.  A declaration that passes validation while saying
nothing useful - permanent with no justification, or a blank owner - defeats
that, so these tests drive the real constructor and assert on the refusals.
"""

from __future__ import annotations

import pytest

from ..retention import (
    ArtifactDeclaration,
    RetentionDeclarationError,
    RetentionDisposition,
)


def _declaration(
    *,
    name: str = "gateway-runtime-log",
    root: str = "<a2a_home>/runtime",
    owner: str = "gateway",
    disposition: RetentionDisposition = RetentionDisposition.BOUNDED_BY_SIZE,
    mechanism: str = "rotating handler, 10 MiB across 6 generations",
    reason: str | None = None,
) -> ArtifactDeclaration:
    """Build a valid declaration, overriding one field at a time."""
    return ArtifactDeclaration(
        name=name,
        root=root,
        owner=owner,
        disposition=disposition,
        mechanism=mechanism,
        reason=reason,
    )


def test_a_bounded_declaration_is_accepted() -> None:
    """The ordinary case constructs and reports itself as bounded."""
    declaration = _declaration()

    assert declaration.is_bounded is True
    assert declaration.disposition is RetentionDisposition.BOUNDED_BY_SIZE


def test_permanence_without_a_reason_is_refused() -> None:
    """Permanence must be justified, because silence is how it becomes a default."""
    with pytest.raises(RetentionDeclarationError, match="without a reason"):
        _declaration(disposition=RetentionDisposition.PERMANENT)


def test_permanence_with_a_reason_is_accepted_and_reports_unbounded() -> None:
    """A justified permanent artifact is legitimate and says so."""
    declaration = _declaration(
        disposition=RetentionDisposition.PERMANENT,
        mechanism="nothing removes it",
        reason="the record is the audit trail the operator relies on after a crash",
    )

    assert declaration.is_bounded is False


def test_a_reason_on_a_bounded_declaration_is_refused() -> None:
    """A field that would never be read is a defect, not a harmless extra."""
    with pytest.raises(RetentionDeclarationError, match="would never be read"):
        _declaration(reason="kept for forensics")


def test_a_blank_name_is_refused() -> None:
    """A declaration with no identifier cannot be enumerated."""
    with pytest.raises(RetentionDeclarationError, match="non-empty name"):
        _declaration(name="   ")


def test_a_blank_root_is_refused() -> None:
    """A declaration that does not say where the artifact lands is useless."""
    with pytest.raises(RetentionDeclarationError, match="non-empty root"):
        _declaration(root="   ")


def test_a_blank_owner_is_refused() -> None:
    """An artifact nobody owns is the state this package exists to prevent."""
    with pytest.raises(RetentionDeclarationError, match="non-empty owner"):
        _declaration(owner="   ")


def test_a_blank_mechanism_is_refused() -> None:
    """A stated lifetime with nothing enforcing it is an aspiration, not a policy."""
    with pytest.raises(RetentionDeclarationError, match="non-empty mechanism"):
        _declaration(mechanism="   ")


def test_every_disposition_is_expressible() -> None:
    """Each vocabulary member constructs, so none is decorative."""
    for disposition in RetentionDisposition:
        reason = (
            "justified for this test"
            if disposition is RetentionDisposition.PERMANENT
            else None
        )
        declaration = _declaration(disposition=disposition, reason=reason)

        assert declaration.disposition is disposition
        assert declaration.is_bounded is (
            disposition is not RetentionDisposition.PERMANENT
        )
