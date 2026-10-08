"""Native gateway attachment proves worker provenance without taking ownership."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..testing import foreign_worker, free_port

if TYPE_CHECKING:
    from pathlib import Path


def test_provenance_mismatch_fails_closed_without_eviction(
    tmp_path: Path,
) -> None:
    """An attach-only gateway refuses a foreign-gateway worker and never evicts it.

    The attach-only profile is unarmed with ``auto_spawn=False``: it attaches only to
    a worker that declares THIS gateway as its heartbeat target. A worker on the
    port declaring a different ``gateway_url`` is a provenance mismatch and must
    fail closed - not adopted - without any eviction, because the attach path
    never spawns and eviction lives only on the spawn path.

    Discriminating on both halves against a real worker process:

    - Fails closed: ``ensure_worker`` leaves ``spawned`` False. Degrade the
      provenance check to a bare health probe and the foreign worker is adopted,
      flipping this to True.
    - Without eviction: the worker receives only ``GET /health`` and survives.
      Any ``POST /admin/shutdown`` would mean the attach-only profile tried to evict
      an independently managed worker it does not own.
    """
    from ..control.config import settings
    from ..control.worker_management import LazyWorkerSpawner

    port = free_port()
    foreign_gateway_url = "http://127.0.0.1:2"
    assert foreign_gateway_url.rstrip("/") != settings.gateway_url.rstrip("/"), (
        "the modeled mismatch must actually differ from this gateway's URL"
    )
    body = {"status": "ok", "service": "worker", "gateway_url": foreign_gateway_url}

    request_log = tmp_path / f"worker-requests-{port}.log"
    with foreign_worker(port, body, request_log=request_log) as worker:
        spawner = LazyWorkerSpawner(
            f"http://127.0.0.1:{port}", port, auto_spawn=False, internal_token=None
        )
        asyncio.run(spawner.ensure_worker())

        # Fails closed: the foreign-gateway worker is not adopted as ours.
        assert spawner.spawned is False

        # Without eviction: only health provenance reads, never a shutdown, and
        # the independently managed worker survives untouched.
        requests = request_log.read_text(encoding="utf-8").splitlines()
        assert requests, "the gateway never even probed the worker port"
        assert all(line.startswith("GET /health") for line in requests), requests
        assert worker.poll() is None, (
            "the independently managed worker must not be evicted"
        )


def test_matching_provenance_attaches(tmp_path: Path) -> None:
    """The same attach path DOES adopt a same-gateway worker (discriminator).

    Proves the refusal above is provenance-specific, not a harness that always
    fails: a worker declaring THIS gateway's URL is adopted (``spawned`` True)
    through the identical unarmed ``ensure_worker`` seam, again without any
    eviction.
    """
    from ..control.config import settings
    from ..control.worker_management import LazyWorkerSpawner

    port = free_port()
    body = {"status": "ok", "service": "worker", "gateway_url": settings.gateway_url}

    request_log = tmp_path / f"worker-requests-{port}.log"
    with foreign_worker(port, body, request_log=request_log) as worker:
        spawner = LazyWorkerSpawner(
            f"http://127.0.0.1:{port}", port, auto_spawn=False, internal_token=None
        )
        asyncio.run(spawner.ensure_worker())

        assert spawner.spawned is True
        assert spawner.process is None
        requests = request_log.read_text(encoding="utf-8").splitlines()
        assert all(line.startswith("GET /health") for line in requests), requests
        assert worker.poll() is None
