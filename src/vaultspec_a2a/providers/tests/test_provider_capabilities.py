"""Direct contract tests for execution-mode capability evidence."""

from __future__ import annotations

import pytest

from ..provider_capabilities import (
    Capability,
    CapabilityBlock,
    CapabilityBlocker,
    CapabilityEvidence,
    CapabilityMatrix,
    CapabilityProof,
    CapabilityStatus,
    PermissionMode,
)
from ..provider_catalog import ProviderCatalogKey


def test_complete_matrix_keeps_each_capability_distinct() -> None:
    key = ProviderCatalogKey("kimi", "native-acp")
    records = tuple(
        CapabilityEvidence(
            key=key,
            capability=capability,
            upstream_supported=True,
            support_reason="Vendor documentation records upstream support.",
        )
        for capability in Capability
    )

    matrix = CapabilityMatrix(key=key, records=records)

    assert (
        matrix.record(Capability.WEB_SEARCH).status
        is CapabilityStatus.SUPPORTED_UNPROVEN
    )
    assert {record.capability for record in matrix.records} == set(Capability)


def test_proof_requires_its_exact_lane_and_capability() -> None:
    key = ProviderCatalogKey("kimi", "native-acp")
    proof = CapabilityProof(
        key=key,
        capability=Capability.MCP_TOOLS,
        test_reference="src/vaultspec_a2a/providers/tests/test_kimi_harness_wiring.py",
        reason="The real ACP path composes the injected MCP server.",
    )

    evidence = CapabilityEvidence(
        key=key,
        capability=Capability.MCP_TOOLS,
        upstream_supported=True,
        support_reason="The native ACP contract accepts session MCP servers.",
        proof=proof,
    )

    assert evidence.status is CapabilityStatus.PROVEN

    with pytest.raises(ValueError, match="exact capability"):
        CapabilityEvidence(
            key=key,
            capability=Capability.NATIVE_READ,
            upstream_supported=True,
            support_reason="The local policy names native read tools.",
            proof=proof,
        )


def test_blocked_evidence_retains_support_and_historical_proof() -> None:
    key = ProviderCatalogKey("kimi", "native-acp")
    evidence = CapabilityEvidence(
        key=key,
        capability=Capability.COMPLETED_TURN,
        upstream_supported=True,
        support_reason="The Kimi execution mode supports turns upstream.",
        proof=CapabilityProof(
            key=key,
            capability=Capability.COMPLETED_TURN,
            test_reference="src/vaultspec_a2a/providers/tests/test_kimi_acp_conditioning.py",
            reason="A real behavior test completed the exact lane's turn.",
        ),
        blockers=(
            CapabilityBlock(
                kind=CapabilityBlocker.CREDENTIAL,
                reason="No Kimi credential is configured for this runtime.",
            ),
        ),
    )

    assert evidence.status is CapabilityStatus.BLOCKED
    assert evidence.proof is not None


def test_noncredential_blockers_are_typed_and_remain_blocked() -> None:
    key = ProviderCatalogKey("zai", "claude-code-compat")

    evidence = CapabilityEvidence(
        key=key,
        capability=Capability.COMPLETED_TURN,
        upstream_supported=True,
        support_reason="The execution mode supports turns upstream.",
        blockers=(
            CapabilityBlock(
                kind=CapabilityBlocker.ADMISSION,
                reason="No exact-lane completed-turn proof is recorded yet.",
            ),
        ),
    )

    assert evidence.status is CapabilityStatus.BLOCKED


def test_unsupported_evidence_cannot_claim_a_local_proof() -> None:
    key = ProviderCatalogKey("api-provider", "hosted-api")
    proof = CapabilityProof(
        key=key,
        capability=Capability.NATIVE_READ,
        test_reference="src/vaultspec_a2a/providers/tests/test_provider_capabilities.py",
        reason="A test reference cannot establish an unsupported capability.",
    )

    with pytest.raises(ValueError, match="unsupported capability"):
        CapabilityEvidence(
            key=key,
            capability=Capability.NATIVE_READ,
            upstream_supported=False,
            support_reason="The API lane has no local filesystem binding.",
            proof=proof,
        )


def test_permission_mode_requires_its_safe_reason() -> None:
    key = ProviderCatalogKey("kimi", "native-acp")

    evidence = CapabilityEvidence(
        key=key,
        capability=Capability.NATIVE_READ,
        upstream_supported=True,
        support_reason="The native ACP lane exposes read tooling.",
        permission_mode=PermissionMode.EXACT_NAME_READ_ONLY_ALLOWLIST,
        permission_reason=(
            "Autonomous Kimi permission RPC allows exact read names only."
        ),
    )

    assert evidence.permission_mode is PermissionMode.EXACT_NAME_READ_ONLY_ALLOWLIST

    with pytest.raises(ValueError, match="permission_mode requires"):
        CapabilityEvidence(
            key=key,
            capability=Capability.NATIVE_WRITE,
            upstream_supported=True,
            support_reason="The native ACP lane may request write tooling.",
            permission_mode=PermissionMode.DENIED,
        )


def test_matrix_rejects_missing_duplicate_or_cross_lane_records() -> None:
    key = ProviderCatalogKey("kimi", "native-acp")
    records = tuple(
        CapabilityEvidence(
            key=key,
            capability=capability,
            upstream_supported=True,
            support_reason="Upstream support is independently recorded.",
        )
        for capability in Capability
    )

    with pytest.raises(ValueError, match="every capability exactly once"):
        CapabilityMatrix(key=key, records=records[:-1])

    with pytest.raises(ValueError, match="every capability exactly once"):
        CapabilityMatrix(key=key, records=(*records[:-1], records[0]))

    other_key = ProviderCatalogKey("kimi", "claude-code-compat")
    cross_lane = CapabilityEvidence(
        key=other_key,
        capability=Capability.BACKGROUND,
        upstream_supported=True,
        support_reason="This is a different execution mode.",
    )
    with pytest.raises(ValueError, match="exact lane"):
        CapabilityMatrix(key=key, records=(*records[:-1], cross_lane))
