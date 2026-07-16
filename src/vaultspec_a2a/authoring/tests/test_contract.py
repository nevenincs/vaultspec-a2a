"""Tests for the document-authoring contract (authoring-contract ADR).

Pure-logic assertions over the single source of truth, plus a data-sync guard
that the bundled rule file's ``roles:`` tags never drift from the contract. No
mocks; the data-sync test reads the real bundled markdown via the real rules
frontmatter helpers.
"""

from __future__ import annotations

from pathlib import Path

from vaultspec_a2a.authoring.contract import (
    DOCUMENT_AUTHORING_ROLE_SET,
    DOCUMENT_AUTHORING_ROLES,
    DOCUMENT_AUTHORING_TOPOLOGIES,
    is_document_authoring_role,
    is_document_authoring_topology,
)


def test_role_set_is_the_ordered_tuple_deduped() -> None:
    assert frozenset(DOCUMENT_AUTHORING_ROLES) == DOCUMENT_AUTHORING_ROLE_SET
    assert len(DOCUMENT_AUTHORING_ROLE_SET) == len(DOCUMENT_AUTHORING_ROLES)


def test_roles_are_persona_roles_not_agent_ids() -> None:
    """The contract covers persona role names, never ``vaultspec-*`` agent ids."""
    for role in DOCUMENT_AUTHORING_ROLES:
        assert not role.startswith("vaultspec-")


def test_is_document_authoring_role() -> None:
    for role in DOCUMENT_AUTHORING_ROLES:
        assert is_document_authoring_role(role)
    assert not is_document_authoring_role("coder")
    assert not is_document_authoring_role(None)


def test_is_document_authoring_topology_by_string() -> None:
    assert frozenset({"research_adr"}) == DOCUMENT_AUTHORING_TOPOLOGIES
    assert is_document_authoring_topology("research_adr")
    assert not is_document_authoring_topology("star")


def test_is_document_authoring_topology_accepts_strenum_member() -> None:
    """A ``TopologyType`` member is accepted directly (StrEnum hashes as its str)."""
    from vaultspec_a2a.team.team_config import TopologyType

    assert is_document_authoring_topology(TopologyType.RESEARCH_ADR)
    assert not is_document_authoring_topology(TopologyType.STAR)


def test_contract_matches_bundled_rule_file_roles() -> None:
    """CODE is truth: the bundled conventions file's ``roles:`` == the contract.

    Guards against the bundled ``document-authoring-conventions.md`` and the
    contract drifting apart (a role added to one but not the other), which would
    silently break role-scoped rule delivery for the un-tagged role.
    """
    from vaultspec_a2a.context.rules import _read_frontmatter, _roles_from_meta

    bundled = (
        Path(__file__).resolve().parents[2]
        / "context"
        / "presets"
        / "rules"
        / "document-authoring-conventions.md"
    )
    assert bundled.is_file()
    tagged = _roles_from_meta(_read_frontmatter(bundled))
    assert tagged == DOCUMENT_AUTHORING_ROLE_SET
