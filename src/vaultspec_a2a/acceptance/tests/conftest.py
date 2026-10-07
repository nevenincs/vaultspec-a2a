"""Fixtures for the real-process acceptance suite.

One authenticated broker certification stack is booted per test module and shared by
its scenarios; every scenario uses a distinct run id so a shared gateway never
couples independent certifications.

These scenarios certify the provider-INDEPENDENT dashboard gateway contract -
run creation, status projection, cancellation routing, streaming, deletion, and
authentication - which holds whether a run ultimately completes or fails. They
therefore need no deterministic provider backend and run without Docker.
Successful-orchestration and interactive-pause certification, which do need the
provider, live in the service suite.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ._harness import CertifiedGateway, certified_gateway

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(scope="module")
def gateway(tmp_path_factory: pytest.TempPathFactory) -> Iterator[CertifiedGateway]:
    """Boot one real authenticated broker stack for a test module."""
    workdir: Path = tmp_path_factory.mktemp("acceptance-stack")
    with certified_gateway(workdir) as running:
        yield running
