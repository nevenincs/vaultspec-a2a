"""Unit coverage for the run-admission drain gate state machine.

Pure-logic isolation of the gate: real ``asyncio`` semantics, no external
service. The integrated real-descendant containment proof lives in the desktop
owned-process-tree test.
"""

import asyncio

import pytest

from vaultspec_a2a.control.drain import AdmissionState, DrainGate


@pytest.mark.asyncio
async def test_admit_registers_active_run_while_open() -> None:
    gate = DrainGate()
    result = await gate.admit("run-1")
    assert result.admitted is True
    assert result.state is AdmissionState.OPEN
    assert result.active_runs == 1
    assert gate.is_active("run-1")
    assert gate.active_run_count == 1


@pytest.mark.asyncio
async def test_admit_is_idempotent_for_same_run() -> None:
    gate = DrainGate()
    await gate.admit("run-1")
    result = await gate.admit("run-1")
    assert result.admitted is True
    assert gate.active_run_count == 1


@pytest.mark.asyncio
async def test_close_admission_refuses_new_runs() -> None:
    gate = DrainGate()
    await gate.admit("run-1")
    state = await gate.close_admission()
    assert state is AdmissionState.DRAINING
    assert gate.is_draining is True

    refused = await gate.admit("run-2")
    assert refused.admitted is False
    assert refused.state is AdmissionState.DRAINING
    assert refused.reason is not None
    # The refused run never joins the active set.
    assert gate.active_run_count == 1
    assert not gate.is_active("run-2")


@pytest.mark.asyncio
async def test_release_reaches_quiescence() -> None:
    gate = DrainGate()
    await gate.admit("run-1")
    await gate.admit("run-2")
    await gate.release("run-1")
    assert gate.active_run_count == 1
    await gate.release("run-2")
    assert gate.active_run_count == 0


@pytest.mark.asyncio
async def test_release_is_idempotent() -> None:
    gate = DrainGate()
    await gate.admit("run-1")
    await gate.release("run-1")
    await gate.release("run-1")
    assert gate.active_run_count == 0


@pytest.mark.asyncio
async def test_drain_returns_immediately_when_idle() -> None:
    gate = DrainGate()
    result = await gate.drain(timeout=1.0)
    assert result.quiescent is True
    assert result.active_runs == 0
    assert gate.is_draining is True


@pytest.mark.asyncio
async def test_drain_times_out_while_run_active() -> None:
    gate = DrainGate()
    await gate.admit("run-1")
    result = await gate.drain(timeout=0.05)
    assert result.quiescent is False
    assert result.active_runs == 1
    assert result.waited_seconds >= 0.05


@pytest.mark.asyncio
async def test_drain_completes_when_active_run_released_concurrently() -> None:
    gate = DrainGate()
    await gate.admit("run-1")

    async def _release_soon() -> None:
        await asyncio.sleep(0.02)
        await gate.release("run-1")

    releaser = asyncio.create_task(_release_soon())
    result = await gate.drain(timeout=2.0)
    await releaser
    assert result.quiescent is True
    assert result.active_runs == 0


@pytest.mark.asyncio
async def test_close_admission_is_atomic_against_concurrent_admits() -> None:
    gate = DrainGate()

    async def _admit(run_id: str) -> bool:
        return (await gate.admit(run_id)).admitted

    # Close interleaved with a burst of admits: every admit is either fully
    # granted (and counted) or fully refused; the closed flag is never observed
    # half-applied.
    await gate.close_admission()
    outcomes = await asyncio.gather(*[_admit(f"run-{i}") for i in range(20)])
    assert not any(outcomes)
    assert gate.active_run_count == 0
