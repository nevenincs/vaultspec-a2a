"""Containment proofs for the served vocabularies that were narrowed.

Narrowing a served field from a bare string to an enumeration is a breaking
change for any consumer the moment the service emits a value the enumeration
does not contain: the response stops serialising and the caller gets a fault
where it used to get a field. These tests are the evidence that no such value
exists, and they prove it two independent ways.

The first way is a CAPTURE. Every value in ``LIVE_*`` below was read off a
running gateway on 2026-08-05 - six real runs in ``completed``, ``failed`` and
``reconciling``, twenty discovered presets, and the service-state and readiness
surfaces - and is asserted to survive the narrowed field. A capture proves what
the system really emitted; it cannot prove what it might emit, because six runs
cannot exhibit every reachable value.

The second way closes that gap by DRIVING THE PRODUCER. Each vocabulary's real
projection function is run across its own input domain - every thread status,
every research_adr node the topology declares, every branch of the replay
contract - and every value it returns is asserted to be a member. This is the
half that would catch a producer emitting something the enumeration lacks, and
it is deliberately not written against a list of expected outputs: it asserts
membership of whatever the implementation actually returns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...control.worker_status import WorkerConnectionStatus
from ...graph.enums import (
    RESEARCH_ADR_NODE_PHASE,
    SemanticPhase,
    research_adr_semantic_phase,
)
from ...providers.conditions import ProviderCondition
from ...team.preset_origin import PresetOrigin
from ...team.team_config import TopologyType
from ...thread.enums import (
    ApprovalStatus,
    DegradedReason,
    RepairStatus,
    ReplayStatus,
    ThreadStatus,
)
from ..schemas.gateway import (
    PresetSummary,
    RunStatusResponse,
    ServiceStateResponse,
    TopologyPosition,
)

if TYPE_CHECKING:
    from enum import StrEnum

# --- The capture -----------------------------------------------------------
#
# Read from http://127.0.0.1:18100 on 2026-08-05 over /v1/runs?state=all,
# /v1/runs/{id} for all six runs, /v1/presets and /v1/service. These are
# observations, never expectations: a value here is in the list because the
# service was seen to serve it.

LIVE_REPAIR_STATUS = {"healthy", "needs_reconciliation"}
LIVE_EXECUTION_READINESS = {"healthy", "needs_reconciliation"}
LIVE_PROVIDER_CONDITION = {"unknown"}
LIVE_SEMANTIC_PHASE = {"completed", "failed", "recovery_required"}
LIVE_TOPOLOGY = {"pipeline", "pipeline_loop", "research_adr", "star"}
LIVE_ORIGIN = {"bundled", "test_mock"}
LIVE_WORKER_STATUS = {"up"}
LIVE_DEGRADED_REASON = {"execution_state_projection_missing"}


@pytest.mark.parametrize(
    ("captured", "enumeration"),
    [
        (LIVE_REPAIR_STATUS, RepairStatus),
        (LIVE_EXECUTION_READINESS, RepairStatus),
        (LIVE_PROVIDER_CONDITION, ProviderCondition),
        (LIVE_SEMANTIC_PHASE, SemanticPhase),
        (LIVE_TOPOLOGY, TopologyType),
        (LIVE_ORIGIN, PresetOrigin),
        (LIVE_WORKER_STATUS, WorkerConnectionStatus),
        (LIVE_DEGRADED_REASON, DegradedReason),
    ],
)
def test_captured_live_values_are_contained_in_the_declared_enumeration(
    captured: set[str], enumeration: type[StrEnum]
) -> None:
    """Every value the live service was seen to serve is a declared member."""
    declared = {member.value for member in enumeration}
    assert captured <= declared, (
        f"{enumeration.__name__} omits live-served values: {captured - declared}"
    )


def test_narrowed_run_status_accepts_every_captured_combination() -> None:
    """The narrowed model serialises the values the live runs actually carried.

    Containment as a set relation is necessary but not sufficient: the field has
    to accept the value through the model that serves it. This drives the real
    response model with the captured strings rather than with members, which is
    what a route handler passing a database column does.
    """
    for repair in sorted(LIVE_REPAIR_STATUS):
        for phase in sorted(LIVE_SEMANTIC_PHASE):
            response = RunStatusResponse(
                run_id="captured-run",
                status=ThreadStatus.COMPLETED,
                semantic_phase=phase,
                topology=TopologyPosition(),
                repair_status=repair,
                execution_readiness=repair,
                provider_condition="unknown",
                degraded_reasons=sorted(LIVE_DEGRADED_REASON),
            )
            assert response.repair_status is RepairStatus(repair)
            assert response.semantic_phase is SemanticPhase(phase)


def test_narrowed_preset_and_service_accept_the_captured_values() -> None:
    """The preset listing and service state accept what they were seen to serve."""
    for topology in sorted(LIVE_TOPOLOGY):
        for origin in sorted(LIVE_ORIGIN):
            preset = PresetSummary(
                id="captured", loadable=True, topology=topology, origin=origin
            )
            assert preset.topology is TopologyType(topology)
            assert preset.origin is PresetOrigin(origin)

    for status in sorted(LIVE_WORKER_STATUS):
        service = ServiceStateResponse(
            service_version="0.3.0",
            status="ready",
            ready=True,
            can_accept_run=True,
            gateway_pid=1,
            worker_status=status,
        )
        assert service.worker_status is WorkerConnectionStatus(status)


# --- Driving the producers -------------------------------------------------


def test_semantic_phase_projection_only_ever_returns_declared_members() -> None:
    """Drive the real projection across its whole input domain.

    The domain is every thread status crossed with every repair posture and
    every node name the projection can be handed - the research_adr structural
    nodes, their mounted forms, the fan-out prefix, and the non-topology names
    that must yield no phase. The assertion is membership of whatever comes
    back, so a projection that grew a new return value would fail here rather
    than at a consumer.
    """
    from ...control.thread_state_service import project_semantic_phase

    node_names = [
        *RESEARCH_ADR_NODE_PHASE,
        *(f"mount_{node}" for node in RESEARCH_ADR_NODE_PHASE),
        "research_dispatch_0",
        "mount_research_dispatch_1",
        "supervisor",
        "coder",
        "__end__",
        "",
    ]
    declared = set(SemanticPhase)

    observed: set[SemanticPhase] = set()
    for status in ThreadStatus:
        for repair in [None, *(member.value for member in RepairStatus)]:
            for node in node_names:
                phase = project_semantic_phase(
                    status=status.value, next_nodes=[node], repair_status=repair
                )
                assert phase in declared, (
                    f"undeclared phase {phase!r} from status={status.value} "
                    f"repair={repair} node={node}"
                )
                observed.add(phase)
            empty = project_semantic_phase(
                status=status.value, next_nodes=[], repair_status=repair
            )
            assert empty in declared
            observed.add(empty)

    # The projection must be able to reach more than the terminal handful, or
    # this sweep would pass while proving almost nothing about the vocabulary.
    assert len(observed) > len(_SEMANTIC_TERMINAL_MEMBERS)


_SEMANTIC_TERMINAL_MEMBERS = {
    SemanticPhase.COMPLETED,
    SemanticPhase.FAILED,
    SemanticPhase.CANCELLED,
}


def test_node_phase_map_and_prefix_resolution_stay_inside_the_vocabulary() -> None:
    """Every phase the shared node map can yield is a declared member."""
    declared = set(SemanticPhase)
    assert set(RESEARCH_ADR_NODE_PHASE.values()) <= declared

    for node in RESEARCH_ADR_NODE_PHASE:
        assert research_adr_semantic_phase(node) in declared
        assert research_adr_semantic_phase(f"mount_{node}") in declared
    assert research_adr_semantic_phase("research_dispatch_2") in declared
    # A node outside the topology must still yield no phase at all, so the
    # narrowing never pressures the projection into inventing one.
    assert research_adr_semantic_phase("supervisor") is None
    assert research_adr_semantic_phase("__end__") is None


def test_replay_contract_only_ever_writes_declared_members() -> None:
    """Drive every branch of the replay contract and check what it writes."""
    from dataclasses import dataclass, field

    from ...thread.snapshots import finalize_snapshot_replay_status

    @dataclass
    class _Snapshot:
        replay_status: str = ReplayStatus.UNKNOWN.value
        snapshot_complete: bool = True
        degraded_reasons: list[str] = field(default_factory=list)
        repair_status: str = RepairStatus.HEALTHY.value
        execution_readiness: str = RepairStatus.HEALTHY.value

    declared_replay = {member.value for member in ReplayStatus}
    declared_reasons = {member.value for member in DegradedReason}

    observed: set[str] = set()
    for loaded in (True, False):
        for error in (True, False):
            for present in (True, False):
                for status in ThreadStatus:
                    result = finalize_snapshot_replay_status(
                        _Snapshot(),
                        checkpoint_loaded=loaded,
                        checkpoint_error=error,
                        checkpoint_present=present,
                        thread_status=status.value,
                    )
                    assert result.replay_status in declared_replay, (
                        f"undeclared replay status {result.replay_status!r}"
                    )
                    assert set(result.degraded_reasons) <= declared_reasons, (
                        "undeclared degraded reason from the replay contract: "
                        f"{set(result.degraded_reasons) - declared_reasons}"
                    )
                    observed.add(result.replay_status)

    # All four members must be reachable, otherwise a member with no producer
    # is sitting in the vocabulary and this sweep is not exercising the branches.
    assert observed == declared_replay


def test_approval_status_write_gate_admits_only_declared_members() -> None:
    """The durable write path refuses a value outside the vocabulary.

    This is what makes the served narrowing safe without a large historical
    corpus to sample: the column physically cannot hold a non-member, because
    the coercion every writer goes through constructs the enum and raises
    otherwise. Proven against the real coercion, not asserted.
    """
    from ...database._helpers import _coerce_approval_status

    for member in ApprovalStatus:
        assert _coerce_approval_status(member.value) is member
        assert _coerce_approval_status(member) is member
    with pytest.raises(ValueError):
        _coerce_approval_status("archived")


def test_repair_status_write_gate_admits_only_declared_members() -> None:
    """The same proof for the vocabulary repair_status/execution_readiness share."""
    from ...database._helpers import _coerce_repair_status

    for member in RepairStatus:
        assert _coerce_repair_status(member.value) is member
        assert _coerce_repair_status(member) is member
    with pytest.raises(ValueError):
        _coerce_repair_status("reconciling")


def test_degraded_reason_vocabulary_covers_every_producer_in_the_tree() -> None:
    """Every reason literal appended anywhere in production is a declared member.

    Sweeps the source rather than trusting a hand-kept list, because the whole
    hazard this guards is a producer added in a module the reviewer did not
    open. A literal appended to a snapshot's degradation list that is not a
    member here is exactly the value that would break the field once narrowed.
    """
    import re
    from pathlib import Path

    package_root = Path(__file__).resolve().parents[2]
    appended = re.compile(r'degraded_reasons\.append\(\s*"([a-z_]+)"\s*\)')

    declared = {member.value for member in DegradedReason}
    found: dict[str, str] = {}
    for source in package_root.rglob("*.py"):
        if "tests" in source.parts:
            continue
        for literal in appended.findall(source.read_text(encoding="utf-8")):
            found[literal] = str(source.relative_to(package_root))

    undeclared = {
        value: where for value, where in found.items() if value not in declared
    }
    assert not undeclared, f"degraded reasons with no declared member: {undeclared}"
    # A sweep that found nothing would pass vacuously.
    assert len(found) >= 8, f"reason sweep found only {len(found)} literals"


# --- One declaration per concept -------------------------------------------


def test_each_served_vocabulary_has_exactly_one_declaration_site() -> None:
    """No served vocabulary is declared twice in the package.

    The rule is one declaration per CONCEPT, which is why this checks for a
    second ``class X(StrEnum)`` rather than for a second mention of the name. A
    package facade that re-exports the owning module's type is not a second
    declaration - it is the import surface this codebase requires - and the two
    would be indistinguishable to a check written against names.

    ``AdmissionState`` is deliberately absent from this list: it is declared
    twice on purpose, for a drain gate and for provider admission, which are
    genuinely different concepts that collide by name. Adding it here would
    convert that distinction into a defect report and invite a merge that
    destroys it.
    """
    import re
    from collections import defaultdict
    from pathlib import Path

    owned = {
        "ApprovalStatus": "thread/enums.py",
        "AuthoringCapability": "team/team_config.py",
        "DegradedReason": "thread/enums.py",
        "DocumentCapability": "team/team_config.py",
        "PresetOrigin": "team/preset_origin.py",
        "Provider": "graph/enums.py",
        "ProviderCondition": "providers/conditions.py",
        "RepairStatus": "thread/enums.py",
        "ReplayStatus": "thread/enums.py",
        "SemanticPhase": "graph/enums.py",
        "ThreadStatus": "thread/enums.py",
        "TopologyType": "team/team_config.py",
        "WorkerConnectionStatus": "control/worker_status.py",
    }

    package_root = Path(__file__).resolve().parents[2]
    declaration = re.compile(r"^class ([A-Za-z_]+)\(StrEnum\):", re.MULTILINE)

    sites: defaultdict[str, list[str]] = defaultdict(list)
    for source in package_root.rglob("*.py"):
        if "tests" in source.parts:
            continue
        for name in declaration.findall(source.read_text(encoding="utf-8")):
            if name in owned:
                sites[name].append(source.relative_to(package_root).as_posix())

    for name, expected_home in owned.items():
        assert sites[name] == [expected_home], (
            f"{name} should be declared once at {expected_home}, found {sites[name]}"
        )


def test_the_two_admission_state_concepts_remain_separately_declared() -> None:
    """The same-name/different-concept pair must NOT have been consolidated.

    Written as a positive requirement rather than left to reviewer memory,
    because the tidying instinct that would merge these reads as a cleanup. The
    member sets are disjoint, which is the evidence that they answer different
    questions and that a merged type could not serve either honestly.
    """
    from ...control.drain import AdmissionState as DrainAdmissionState
    from ...providers.provider_catalog import AdmissionState as CatalogAdmissionState

    assert DrainAdmissionState is not CatalogAdmissionState
    drain_members = {member.value for member in DrainAdmissionState}
    catalog_members = {member.value for member in CatalogAdmissionState}
    assert not drain_members & catalog_members, (
        "the two AdmissionState vocabularies have started to overlap, which is "
        "the first symptom of a merge"
    )


# --- Preset capability vocabularies ----------------------------------------

LIVE_AUTHORING_CAPABILITY = {"coding", "document_authoring"}
LIVE_DOCUMENT_CAPABILITY = {
    "architecture_decision",
    "plan_document",
    "research_document",
}


def test_capability_vocabularies_contain_what_the_listing_serves() -> None:
    """The two preset capability enumerations cover the whole live listing.

    Both are sole-producer vocabularies, so this drives the producers over their
    whole input domain rather than sampling: the returned set IS the served set,
    and the twenty-preset capture agreed with it member for member.

    The two domains differ because the two keyings now differ. The coarse field
    is driven over every DISCOVERABLE PRESET, since it reads declared roles; the
    document array is driven over every TOPOLOGY, since it still reads topology.
    """
    from ...team.team_config import (
        AuthoringCapability,
        DocumentCapability,
        authoring_capability,
        discover_team_preset_ids,
        load_team_config,
        supported_capabilities,
    )

    produced_coarse: set[str] = set()
    for preset_id in discover_team_preset_ids():
        try:
            team = load_team_config(preset_id)
        except Exception:
            continue
        produced_coarse.add(authoring_capability(team).value)
    produced_documents = {
        capability.value
        for topology in TopologyType
        for capability in supported_capabilities(topology)
    }

    assert produced_coarse <= {member.value for member in AuthoringCapability}
    assert produced_documents <= {member.value for member in DocumentCapability}
    # The capture and the producers must agree: a member the producer can reach
    # but the live listing never showed would mean the sweep missed a topology.
    assert produced_coarse == LIVE_AUTHORING_CAPABILITY
    assert produced_documents == LIVE_DOCUMENT_CAPABILITY


def test_every_declared_capability_member_has_a_producing_topology() -> None:
    """No member advertises a deliverable no preset can deliver.

    The inverse of containment, and the one that catches an enumeration grown
    aspirationally: a document kind added here with no topology producing it
    would be served to a client as an available capability.
    """
    from ...team.team_config import (
        AuthoringCapability,
        DocumentCapability,
        authoring_capability,
        discover_team_preset_ids,
        load_team_config,
        supported_capabilities,
    )

    reachable_coarse: set[AuthoringCapability] = set()
    for preset_id in discover_team_preset_ids():
        try:
            team = load_team_config(preset_id)
        except Exception:
            continue
        reachable_coarse.add(authoring_capability(team))
    reachable_documents = {
        capability
        for topology in TopologyType
        for capability in supported_capabilities(topology)
    }
    assert reachable_coarse == set(AuthoringCapability)
    assert reachable_documents == set(DocumentCapability)


def test_the_capability_and_mechanism_keyings_disagree_on_exactly_two_presets() -> None:
    """Pin which presets the capability and mechanism questions answer differently.

    Two questions are asked of every preset and they are NOT the same question.
    ``authoring_capability`` asks "does this preset author documents?" and keys on
    declared ROLES. The submitter gate in ``worker/graph_lifecycle.py`` asks "does
    this preset submit over the direct worker-to-engine path?" and keys on
    TOPOLOGY. Both are correct, and where they disagree BOTH answers are true.

    This test asserts neither is right - it pins the disagreement SET. The set is
    the thing a future reader will be tempted to eliminate, because two
    derivations of what looks like one fact disagreeing reads as a bug. Growing
    or shrinking it should be a reviewed decision, not a side effect.

    The two members, and why each is deliberate:

    ``vaultspec-doc-editor`` authors documents (role ``doc-editor``) but submits
    through the model's bridged tool rather than the direct path, so it is
    document-authoring WITHOUT a submitter. This is the case the re-key existed
    to fix, and the disagreement here is the fix working.

    ``deterministic-failure`` reuses the REAL researcher and synthesist agents to
    script a guaranteed graph-budget failure, so it DECLARES document-authoring
    roles while structurally never finishing. It reads document-authoring by role
    and gets no submitter by topology. It is certification scaffolding that the
    preset listing should exclude by declared classification rather than by
    identifier - until it does, this preset is why ``supported_capabilities``
    deliberately still keys on topology: keying OUTPUTS off roles would advertise
    three deliverables this preset cannot produce.
    """
    from ...authoring.contract import is_document_authoring_topology
    from ...team.team_config import (
        AuthoringCapability,
        authoring_capability,
        discover_team_preset_ids,
        load_team_config,
    )

    disagreeing: set[str] = set()
    for preset_id in discover_team_preset_ids():
        try:
            team = load_team_config(preset_id)
        except Exception:
            continue
        authors_documents = (
            authoring_capability(team) is AuthoringCapability.DOCUMENT_AUTHORING
        )
        uses_direct_submitter = is_document_authoring_topology(team.topology.type)
        if authors_documents != uses_direct_submitter:
            disagreeing.add(preset_id)

    assert disagreeing == {"vaultspec-doc-editor", "deterministic-failure"}, (
        "the capability and mechanism keyings now disagree on a different set of "
        f"presets than recorded: {sorted(disagreeing)}"
    )
