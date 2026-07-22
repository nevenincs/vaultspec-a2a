"""A gateway and its worker must be able to prove they belong together.

Pairing was previously inferred from a URL. A URL cannot distinguish a gateway
from its own restart on the same port, so a worker left over from a previous
incarnation reported the correct target and looked correctly paired - the
condition that let dispatch reach a foreign worker.

These tests pin the identity that makes the distinction possible: one value per
gateway process, and a generation that advances per spawn attempt.
"""

from __future__ import annotations

import asyncio

from vaultspec_a2a.control.worker_management import (
    GATEWAY_LIFETIME_ENV,
    GATEWAY_LIFETIME_ID,
    WORKER_GENERATION_ENV,
    LazyWorkerSpawner,
)


def _spawner() -> LazyWorkerSpawner:
    return LazyWorkerSpawner(
        worker_url="http://127.0.0.1:19101",
        worker_port=19101,
        auto_spawn=False,
    )


def test_the_lifetime_identity_is_a_stable_non_empty_value() -> None:
    """One value per process: reading it twice must not mint a new one."""
    assert GATEWAY_LIFETIME_ID
    assert len(GATEWAY_LIFETIME_ID) == 32

    import vaultspec_a2a.control.worker_management as worker_management

    assert worker_management.GATEWAY_LIFETIME_ID == GATEWAY_LIFETIME_ID


def test_the_env_names_are_distinct_and_namespaced() -> None:
    """Two identities travel to the worker; they must not collide."""
    assert GATEWAY_LIFETIME_ENV != WORKER_GENERATION_ENV
    assert GATEWAY_LIFETIME_ENV.startswith("VAULTSPEC_")
    assert WORKER_GENERATION_ENV.startswith("VAULTSPEC_")


def test_a_fresh_spawner_has_issued_no_generation() -> None:
    """Generation zero means no worker has been spawned by this gateway."""
    assert _spawner().generation == 0


def test_each_generation_request_yields_a_distinct_increasing_value() -> None:
    """A restart must not reuse the generation of the worker it replaces."""
    spawner = _spawner()

    issued = [spawner.next_generation() for _ in range(5)]

    assert issued == [1, 2, 3, 4, 5]
    assert spawner.generation == 5


def test_the_generation_counter_is_per_spawner_not_global() -> None:
    """Two gateways counting into one another would make the value meaningless."""
    first, second = _spawner(), _spawner()

    first.next_generation()
    first.next_generation()

    assert first.generation == 2
    assert second.generation == 0


def test_concurrent_generation_requests_never_collide() -> None:
    """The watchdog and the lazy path can both request one; neither may duplicate."""
    spawner = _spawner()

    async def _drive() -> list[int]:
        return await asyncio.gather(
            *(asyncio.to_thread(spawner.next_generation) for _ in range(20))
        )

    issued = asyncio.run(_drive())

    assert sorted(issued) == list(range(1, 21))
    assert len(set(issued)) == 20
