"""Worker readiness uses both live reachability and adoption authority."""

from ...api.schemas.gateway import WorkerLifecycleState
from ..health import _desktop_worker_state
from ..worker_status import WorkerConnectionStatus


def test_unspawned_worker_requires_adoption_proof() -> None:
    shared: dict[str, object] = {
        "worker_spawned": False,
        "worker_status": WorkerConnectionStatus.UNKNOWN,
        "worker_connected": False,
    }
    state, reason = _desktop_worker_state(shared, True, True)
    assert state is WorkerLifecycleState.READY
    assert reason is None

    state, reason = _desktop_worker_state(shared, True, False)
    assert state is WorkerLifecycleState.COLD
    assert reason == "worker is cold; starts on first execution demand"


def test_pending_worker_uses_heartbeat_only_when_probe_has_no_verdict() -> None:
    shared: dict[str, object] = {
        "worker_spawned": True,
        "worker_status": WorkerConnectionStatus.PENDING,
        "worker_connected": True,
    }
    state, reason = _desktop_worker_state(shared, None, None)
    assert state is WorkerLifecycleState.READY
    assert reason is None

    state, reason = _desktop_worker_state(shared, False, None)
    assert state is WorkerLifecycleState.STARTING
    assert reason is None

    shared["worker_status"] = WorkerConnectionStatus.DOWN
    state, reason = _desktop_worker_state(shared, True, None)
    assert state is WorkerLifecycleState.UNAVAILABLE
    assert reason == "worker is down"
