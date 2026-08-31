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

import time
from typing import TYPE_CHECKING, Any

import pytest

from ...thread.enums import TERMINAL_STATUS_VALUES
from .. import CertifiedGateway, certified_gateway

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
    """Poll ``/v1/runs/{run_id}`` until *predicate* holds; return that snapshot."""
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        response = gateway.status(run_id)
        if response.status_code == 200:
            last = response.json()
            if predicate(last):
                return last
        time.sleep(interval)
    raise AssertionError(
        f"run {run_id} never satisfied the awaited status predicate; last: {last}"
    )


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
