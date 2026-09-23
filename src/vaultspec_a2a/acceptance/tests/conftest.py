"""Fixtures and readiness polling for the real-process acceptance suite.

One armed-desktop certification stack is booted per test module and shared by
its scenarios; every scenario uses a distinct run id so a shared gateway never
couples independent certifications. The polling helpers read only the real
public surface, so a run that never reaches the awaited state trips the timeout
with the last observed body rather than hiding a stall.

These scenarios certify the provider-INDEPENDENT dashboard gateway contract -
run creation, status projection, cancellation routing, streaming, deletion, and
authentication - which holds whether a run ultimately completes or fails. They
therefore need no deterministic provider backend and run without Docker.
Successful-orchestration and interactive-pause certification, which do need the
provider, live in the Compose service suite.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from ...testing.progress import ProgressDeadline, ProgressStalledError, wait_for
from ...thread.enums import TERMINAL_STATUS_VALUES
from ._harness import CertifiedGateway, certified_gateway

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

# The product-safe terminal status strings a public run-status response can carry.


@pytest.fixture(scope="module")
def gateway(tmp_path_factory: pytest.TempPathFactory) -> Iterator[CertifiedGateway]:
    """Boot one real armed-desktop certification stack for a test module."""
    workdir: Path = tmp_path_factory.mktemp("acceptance-stack")
    with certified_gateway(workdir) as running:
        yield running


def wait_for_run_status(
    gateway: CertifiedGateway,
    run_id: str,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout: float = 90.0,
    interval: float = 0.5,
) -> dict[str, Any]:
    """Poll ``/v1/runs/{run_id}`` until *predicate* holds; return that snapshot.

    The wait fails when the run STOPS MOVING, not when it takes a while: a
    snapshot whose status or checkpoint cursor differs from the last one counts
    as progress and renews the window, so *timeout* bounds a SILENCE rather than
    the whole run. A real run on a loaded host is slow in a way no fixed total
    budget can be written for; a wedged one repeats one snapshot and fails after
    a single window with that snapshot attached.
    """
    last: dict[str, Any] | None = None

    def _poll() -> dict[str, Any] | None:
        nonlocal last
        response = gateway.status(run_id)
        if response.status_code != 200:
            return None
        last = response.json()
        return last if last is not None and predicate(last) else None

    def _fingerprint() -> object:
        return None if last is None else (last.get("status"), last.get("last_sequence"))

    try:
        return wait_for(
            _poll,
            deadline=ProgressDeadline(idle_window_s=timeout),
            fingerprint=_fingerprint,
            interval_s=interval,
        )
    except ProgressStalledError as stalled:
        raise AssertionError(
            f"run {run_id} never satisfied the awaited status predicate; "
            f"last: {last} ({stalled})"
        ) from stalled


def wait_for_terminal(
    gateway: CertifiedGateway, run_id: str, *, timeout: float = 90.0
) -> dict[str, Any]:
    """Poll run-status until the run reaches a durable terminal status.

    A terminal status is reached whether the run completes or fails, so this is
    the provider-independent settling point the contract scenarios build on.
    """
    return wait_for_run_status(
        gateway,
        run_id,
        lambda body: body.get("status") in TERMINAL_STATUS_VALUES,
        timeout=timeout,
    )
