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
    "is_document_authoring_role",
    "is_document_authoring_topology",
]

# Ordered: the graph compiler consumes this order (research diverge -> synthesis
# -> adr-author -> doc-reviewer). Matches the bundled
# ``document-authoring-conventions`` rule file's ``roles:`` tags exactly - a
# data-sync test asserts the two never drift (code is the source of truth).
DOCUMENT_AUTHORING_ROLES: tuple[str, ...] = (
    "researcher",
    "synthesist",
    "adr-author",
    "doc-reviewer",
)

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
