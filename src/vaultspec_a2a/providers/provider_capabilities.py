"""Immutable, execution-mode-scoped provider capability evidence.

This module owns only the capability evidence contract.  It deliberately does
not discover a catalog, infer adapter behavior, or admit a lane: those remain
with their existing owners and will be composed into this contract separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .provider_catalog import ProviderCatalogKey

__all__ = [
    "Capability",
    "CapabilityBlock",
    "CapabilityBlocker",
    "CapabilityEvidence",
    "CapabilityMatrix",
    "CapabilityProof",
    "CapabilityStatus",
    "PermissionMode",
]

MAX_TEXT_LENGTH: Final = 1_024


def _required_text(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-blank and already normalized")
    if len(value) > MAX_TEXT_LENGTH:
        raise ValueError(f"{field_name} exceeds the {MAX_TEXT_LENGTH}-character limit")
    return value


class Capability(StrEnum):
    """Capabilities that must be recorded independently for every lane."""

    CATALOG_ENUMERATION = "catalog_enumeration"
    EXACT_SELECTION = "exact_selection"
    COMPLETED_TURN = "completed_turn"
    MCP_TOOLS = "mcp_tools"
    NATIVE_READ = "native_read"
    NATIVE_WRITE = "native_write"
    WEB_SEARCH = "web_search"
    WEB_FETCH = "web_fetch"
    SUBAGENT = "subagent"
    BACKGROUND = "background"


class CapabilityStatus(StrEnum):
    """The state derived from independent support, proof, and blocker facts."""

    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"
    SUPPORTED_UNPROVEN = "supported_unproven"
    PROVEN = "proven"


class CapabilityBlocker(StrEnum):
    """Bounded causes that can presently block otherwise supported behavior."""

    CREDENTIAL = "credential"
    CONFIGURATION = "configuration"
    TRANSPORT = "transport"
    AUTHENTICATION = "authentication"
    CATALOG = "catalog"
    ADMISSION = "admission"
    LOCAL_POLICY = "local_policy"


class PermissionMode(StrEnum):
    """Local permission policy applied to a capability, where one exists."""

    EXACT_NAME_READ_ONLY_ALLOWLIST = "exact_name_read_only_allowlist"
    OPERATOR_APPROVAL = "operator_approval"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class CapabilityBlock:
    """One present blocker with a bounded kind and safe operator-facing reason."""

    kind: CapabilityBlocker
    reason: str

    def __post_init__(self) -> None:
        _required_text(self.reason, "capability blocker reason")


@dataclass(frozen=True, slots=True)
class CapabilityProof:
    """A rerunnable real-behavior proof for one exact capability lane."""

    key: ProviderCatalogKey
    capability: Capability
    test_reference: str
    reason: str

    def __post_init__(self) -> None:
        _required_text(self.test_reference, "capability proof test_reference")
        _required_text(self.reason, "capability proof reason")


@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    """Independent capability facts for one provider execution-mode lane."""

    key: ProviderCatalogKey
    capability: Capability
    upstream_supported: bool
    support_reason: str
    proof: CapabilityProof | None = None
    blockers: tuple[CapabilityBlock, ...] = ()
    permission_mode: PermissionMode | None = None
    permission_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "blockers", tuple(self.blockers))
        _required_text(self.support_reason, "capability support_reason")
        if self.proof is not None:
            if not self.upstream_supported:
                raise ValueError("an unsupported capability cannot carry a proof")
            if self.proof.key != self.key:
                raise ValueError("capability proof must name the exact evidence lane")
            if self.proof.capability is not self.capability:
                raise ValueError("capability proof must name the exact capability")
        blocker_kinds = tuple(blocker.kind for blocker in self.blockers)
        if len(blocker_kinds) != len(set(blocker_kinds)):
            raise ValueError("capability blockers must not repeat a kind")
        if self.permission_mode is None and self.permission_reason is not None:
            raise ValueError("permission_reason requires a permission_mode")
        if self.permission_mode is not None and self.permission_reason is None:
            raise ValueError("permission_mode requires a permission_reason")
        if self.permission_reason is not None:
            _required_text(self.permission_reason, "capability permission_reason")

    @property
    def status(self) -> CapabilityStatus:
        """Return the claim state without conflating any evidence dimension."""
        if not self.upstream_supported:
            return CapabilityStatus.UNSUPPORTED
        if self.blockers:
            return CapabilityStatus.BLOCKED
        if self.proof is not None:
            return CapabilityStatus.PROVEN
        return CapabilityStatus.SUPPORTED_UNPROVEN


@dataclass(frozen=True, slots=True)
class CapabilityMatrix:
    """The complete immutable capability set for one execution-mode lane."""

    key: ProviderCatalogKey
    records: tuple[CapabilityEvidence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        record_capabilities = tuple(record.capability for record in self.records)
        if len(self.records) != len(Capability) or set(record_capabilities) != set(
            Capability
        ):
            raise ValueError(
                "capability matrix must contain every capability exactly once"
            )
        if any(record.key != self.key for record in self.records):
            raise ValueError("capability matrix records must name its exact lane")

    def record(self, capability: Capability) -> CapabilityEvidence:
        """Return the complete evidence record for one declared capability."""
        return next(
            record for record in self.records if record.capability is capability
        )
