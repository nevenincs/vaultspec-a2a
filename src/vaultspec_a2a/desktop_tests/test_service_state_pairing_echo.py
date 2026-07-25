"""Real-process proof that service-state echoes the worker's pairing evidence.

The gateway's readiness surface reports two identities that no addressing fact
can supply: ``gateway_lifetime_id`` - THIS gateway incarnation - and
``worker_paired_gateway_lifetime`` - which incarnation the worker on the private
worker port says spawned it. A consumer holding host and port alone cannot tell
a gateway from its own restart, so the pair is served rather than inferred.

Both proofs run the REAL ``serve`` entrypoint over a migrated application home
and a real ``vaultspec_a2a.worker`` process, and read the answer off the real
authenticated HTTP surface. They are deliberately symmetric - same endpoint,
same fields, same gateway boot recipe - so the only difference between them is
who started the worker holding the port:

- a worker the gateway spawned reports the spawning gateway's own lifetime id,
  and the endpoint serves the two values EQUAL;
- a real worker the gateway did not spawn reports blank, and the endpoint serves
  it blank - never quietly substituting the gateway's own identity.

The second proof is the load-bearing one. Echoing ``gateway_lifetime_id`` into
both fields, or defaulting the worker's field when the worker reports nothing,
satisfies the first proof and fails the second.

No mock, monkeypatch, stub, skip, or expected failure is used; every child is
reaped in a ``finally``.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import httpx

from vaultspec_a2a.control.worker_management import (
    GATEWAY_LIFETIME_ENV,
    GATEWAY_LIFETIME_ID,
    WORKER_GENERATION_ENV,
)

from .test_ownership_prerequisites import (
    _armed_env,
    _armed_serve,
    _prepare,
    _reap,
    _worker_health,
    _worker_ipc_secret,
)
from .test_run_admission import _ATTACH

if TYPE_CHECKING:
    from pathlib import Path


def _service_state(base: str) -> dict[str, Any]:
    """Read the gateway's authenticated service-state body over real HTTP."""
    with httpx.Client(base_url=base, timeout=60.0) as client:
        resp = client.get("/v1/service", headers={"Authorization": f"Bearer {_ATTACH}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, dict), body
    return body


def test_service_state_reports_the_spawning_gateway_for_its_own_worker(
    tmp_path: Path,
) -> None:
    """A gateway-spawned worker is reported paired to the gateway that spawned it.

    The first authenticated demand makes the gateway spawn its own real worker;
    the readiness surface then reports its own lifetime identity and the
    worker's reported one as the SAME value, read off one response so no second
    observation can drift between them.

    Discriminating beyond a self-consistent constant: the served identity is
    also asserted different from this test process's own production-minted
    ``GATEWAY_LIFETIME_ID``. A per-host, per-port, or module-constant identity
    would collide there; only a per-gateway-process one survives. And the echo
    is cross-read against the worker's own health surface, so the value the
    gateway serves is provably the one the worker reported rather than one it
    recomputed from itself.
    """
    with _armed_serve(tmp_path, auto_spawn=True) as (
        app_home,
        _port,
        worker_port,
        base,
    ):
        status, prepared = _prepare(base, "run-service-state-pairing-echo")
        assert status == 201, prepared

        state = _service_state(base)

        gateway_lifetime = state["gateway_lifetime_id"]
        assert isinstance(gateway_lifetime, str) and gateway_lifetime.strip(), state

        # The worker the gateway spawned reports that gateway's incarnation.
        assert state["worker_paired_gateway_lifetime"] == gateway_lifetime, state
        assert state["worker_ready"] is True, state

        # A real spawn attempt, not a placeholder: generations start at one.
        generation = state["worker_generation"]
        assert isinstance(generation, str), state
        assert int(generation) > 0, state

        # LOAD-BEARING: a different real incarnation. This test process minted
        # its own production lifetime identity on import and did not spawn that
        # worker, so the served identity must not be a value both processes
        # would compute.
        assert gateway_lifetime != GATEWAY_LIFETIME_ID

        # The evidence really came off the worker holding the private port: the
        # same two values that worker serves on its own health surface.
        reported = _worker_health(worker_port, _worker_ipc_secret(app_home))
        assert reported["paired_gateway_lifetime"] == gateway_lifetime, reported
        assert reported["worker_generation"] == generation, reported


def test_service_state_reports_blank_for_a_worker_it_did_not_spawn(
    tmp_path: Path,
) -> None:
    """A worker no gateway spawned is reported blank, not as the gateway's own.

    The gateway boots with auto-spawn off, so nothing ever occupies its private
    worker port unless this test puts it there. A REAL production worker is then
    started independently on that port, over the same application home and
    holding the same gateway-minted interprocess-communication secret - so it is
    indistinguishable from the gateway's own worker on every addressing and
    credential fact, and the gateway's probe genuinely reaches it.

    Discriminating in three directions:

    - **Absent before.** With no worker answering, the echoed pairing is
      ``None``. Absent and blank are different answers and the surface keeps
      them apart; collapse them and the blank asserted below stops meaning
      anything.
    - **Answered after.** ``worker_ready`` flips true, so the probe
      demonstrably reached a live worker. Without this the blank echo would be
      equally consistent with no worker at all.
    - **Blank, not borrowed.** The echoed pairing is empty and explicitly not
      the gateway's own served ``gateway_lifetime_id``. Defaulting an unreported
      field to this gateway's identity is exactly the failure that let a foreign
      worker read as correctly paired, and it is caught here and nowhere else.
    """
    with _armed_serve(tmp_path, auto_spawn=False) as (
        app_home,
        port,
        worker_port,
        base,
    ):
        secret = _worker_ipc_secret(app_home)
        assert secret, "the gateway minted no worker IPC secret"

        # Nothing holds the private worker port yet: the pairing fields are
        # absent rather than blank, and readiness says so.
        before = _service_state(base)
        gateway_lifetime = before["gateway_lifetime_id"]
        assert isinstance(gateway_lifetime, str) and gateway_lifetime.strip(), before
        assert before["worker_ready"] is False, before
        assert before["worker_paired_gateway_lifetime"] is None, before
        assert before["worker_generation"] is None, before

        # A real production worker that no gateway spawned. Both pairing
        # variables are cleared so an inherited value from the test host cannot
        # forge the evidence at issue.
        stray_env = _armed_env(
            app_home,
            gateway_port=port,
            worker_port=worker_port,
            auto_spawn=False,
        )
        stray_env["VAULTSPEC_INTERNAL_TOKEN"] = secret
        stray_env.pop(GATEWAY_LIFETIME_ENV, None)
        stray_env.pop(WORKER_GENERATION_ENV, None)
        stray_log = (tmp_path / "stray-worker.log").open("wb")
        stray = subprocess.Popen(
            [sys.executable, "-m", "vaultspec_a2a.worker"],
            env=stray_env,
            stdout=stray_log,
            stderr=subprocess.STDOUT,
        )
        try:
            stranger = _worker_health(worker_port, secret)
            assert stranger["paired_gateway_lifetime"] == "", stranger
            assert stranger["worker_generation"] == "", stranger

            after = _service_state(base)

            # The gateway's own identity is unchanged across both reads: one
            # process, one incarnation, whatever holds the worker port.
            assert after["gateway_lifetime_id"] == gateway_lifetime, after

            # The probe reached a live worker, so the blank below is the
            # worker's answer and not the absence of one.
            assert after["worker_ready"] is True, after

            # LOAD-BEARING: blank, and specifically not this gateway's identity.
            assert after["worker_paired_gateway_lifetime"] == "", after
            assert after["worker_paired_gateway_lifetime"] != gateway_lifetime, after
            assert after["worker_generation"] == "", after
        finally:
            _reap(stray.pid)
            with contextlib.suppress(subprocess.TimeoutExpired):
                stray.wait(timeout=15)
            stray_log.close()
