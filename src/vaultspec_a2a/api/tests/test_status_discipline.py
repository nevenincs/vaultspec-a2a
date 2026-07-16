"""Product run-status speaks role vocabulary, never internal node names.

Real assertions that the gateway run-status contract must not
leak internal LangGraph node names. ``active_agent`` is mapped to the role of the
active worker, orchestration and gate nodes surface as ``None`` rather than their
node name, and the raw ``next_nodes`` projection is absent from the product
topology contract (it survives only in the internal recovery snapshot).
"""

from __future__ import annotations

from types import SimpleNamespace

from vaultspec_a2a.api.routes.gateway import _active_role
from vaultspec_a2a.api.schemas.gateway import TopologyPosition


def _agent(agent_id: str, role: str) -> SimpleNamespace:
    return SimpleNamespace(agent_id=agent_id, role=role)


def test_active_role_maps_worker_node_to_its_role() -> None:
    agents = [_agent("mock-planner", "planner"), _agent("mock-coder-success", "coder")]
    assert _active_role(["mock-coder-success"], agents) == "coder"


def test_active_role_strips_mount_prefix_before_mapping() -> None:
    agents = [_agent("vaultspec-researcher", "researcher")]
    assert _active_role(["mount_vaultspec-researcher"], agents) == "researcher"


def test_active_role_orchestration_node_yields_none_never_node_name() -> None:
    # Internal orchestration/gate nodes have no matching agent; they must resolve
    # to None, never leak "phase_gate"/"diverge"/"supervisor" into the contract.
    agents = [_agent("mock-planner", "planner")]
    result = _active_role(["phase_gate", "diverge", "__end__"], agents)
    assert result is None


def test_active_role_skips_end_and_empty_then_finds_worker() -> None:
    agents = [_agent("mock-planner", "planner")]
    assert _active_role(["__end__", "", "mock-planner"], agents) == "planner"


def test_active_role_empty_next_nodes_is_none() -> None:
    assert _active_role([], [_agent("mock-planner", "planner")]) is None


def test_product_topology_has_no_next_nodes_field() -> None:
    # The product topology contract carries no internal-node-name
    # field. next_nodes was dropped from v1; active_agent stays as the role.
    assert "next_nodes" not in TopologyPosition.model_fields
    assert "active_agent" in TopologyPosition.model_fields
