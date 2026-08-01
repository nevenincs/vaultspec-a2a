"""The document-authoring contract: role names and topologies (authoring-contract ADR).

A single zero-dependency source of truth for WHICH persona roles author vault
documents and WHICH topologies are document-authoring, so the harness verifier,
the run-start policy, the graph compiler, and the worker rule-scoping all agree
instead of each carrying a private copy.

This module imports NOTHING from ``vaultspec_a2a`` by design: it is a leaf, so
any layer (team, control, graph, context, api) can import it without risking an
import cycle.

Role names here are PERSONA roles (``researcher``), never worker agent ids
(``vaultspec-researcher``) - agent-id concerns (token bundles, required roles)
stay in the run-start policy.
"""

from __future__ import annotations

__all__ = [
    "DOCUMENT_AUTHORING_ROLES",
    "DOCUMENT_AUTHORING_ROLE_SET",
    "DOCUMENT_AUTHORING_TOPOLOGIES",
    "RESEARCH_ADR_ROLES",
    "is_document_authoring_role",
    "is_document_authoring_topology",
]

# The research_adr phase machine's REQUIRED roles, in pipeline order (research
# diverge -> synthesis -> adr-author -> plan-author -> doc-reviewer). The graph
# compiler consumes this order and refuses to compile a research_adr preset that
# does not declare a worker for every one of them, so this tuple is narrower than
# the document-role predicate below by design: a solo document lane must NOT drag
# the whole phase machine's roster in behind it.
RESEARCH_ADR_ROLES: tuple[str, ...] = (
    "researcher",
    "synthesist",
    "adr-author",
    "plan-author",
    "doc-reviewer",
)

# Every persona role that puts vault-document CONTENT into the world, whether
# through the phase machine or the solo editing lane. This is the predicate that
# governs role-scoped delivery of the document-authoring conventions, the native
# read-tool floor, and the write-denial guard - all three of which follow the
# content, not the topology. It matches the bundled
# ``document-authoring-conventions`` rule file's ``roles:`` tags exactly; a
# data-sync test asserts the two never drift (code is the source of truth).
DOCUMENT_AUTHORING_ROLES: tuple[str, ...] = (*RESEARCH_ADR_ROLES, "doc-editor")

DOCUMENT_AUTHORING_ROLE_SET: frozenset[str] = frozenset(DOCUMENT_AUTHORING_ROLES)

# Topology-type STRING values. ``TopologyType`` is a ``StrEnum``, so a member
# equals and hashes as its ``str`` value - callers pass enum members directly and
# this leaf needs no ``TopologyType`` import (which would break the zero-internal
# -import invariant).
DOCUMENT_AUTHORING_TOPOLOGIES: frozenset[str] = frozenset({"research_adr"})


def is_document_authoring_role(role: str | None) -> bool:
    """Return whether *role* is a document-authoring persona role (``None`` is not)."""
    return role in DOCUMENT_AUTHORING_ROLE_SET


def is_document_authoring_topology(topology_type: str) -> bool:
    """Return whether *topology_type* is a document-authoring topology.

    Accepts a ``TopologyType`` member directly: a ``StrEnum`` member equals and
    hashes as its ``str`` value, so no stringification is needed at call sites.
    """
    return topology_type in DOCUMENT_AUTHORING_TOPOLOGIES
