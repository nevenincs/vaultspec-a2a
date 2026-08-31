"""A run start never absorbs an unbounded cold provider-catalog build.

A client cannot produce a valid selection without having read the catalog first,
so the warm case is the normal one. The cold case is real anyway - a gateway
restart, or the workspace scope evicted under capacity, between that read and the
start that revalidates against it - and building cold probes every registered
lane over real subprocesses and the network. Absorbing that inside the request is
indistinguishable to the caller from a hung gateway.

Driven against the REAL ``ProviderCatalogService`` over this checkout as a real
workspace, so the lanes discovered are the host's actual ones and the cold build
is the actual work. The budget is squeezed rather than the work slowed: a genuine
cold build cannot finish inside a millisecond, which is the same expiry a
tens-of-seconds build hits against the shipped budget, reached without making the
test wait for it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException

from ...domain_config import domain_config
from ..routes.gateway import _catalog_records_within_budget, provider_catalog_service


@pytest.mark.asyncio(loop_scope="function")
async def test_a_cold_catalog_is_refused_retryably_and_the_retry_is_warm() -> None:
    """An over-budget cold build refuses, keeps building, and serves the retry.

    Both halves are load-bearing and neither proves the contract alone. A refusal
    that also CANCELLED the build would make every retry pay the same cold cost
    and never converge, which reads as a permanently broken workspace rather than
    a busy one; a build that ran to completion inside the request would be the
    unbounded wait this exists to remove.
    """
    app = FastAPI()
    workspace = str(Path(__file__).resolve().parents[3])
    service = provider_catalog_service(app)

    original = domain_config.run_start_catalog_budget_seconds
    domain_config.run_start_catalog_budget_seconds = 0.001
    try:
        with pytest.raises(HTTPException) as refusal:
            await _catalog_records_within_budget(app, workspace)
        assert refusal.value.status_code == 503
        assert "still being built" in str(refusal.value.detail)
    finally:
        domain_config.run_start_catalog_budget_seconds = original

    # The shielded build outlived the refusal. Read through the SERVICE the
    # refused call used: a populated per-lane cache is what makes the retry warm,
    # and reading it any other way would prove nothing about that cache.
    records = await service.records(workspace)
    assert records, "the detached build populated no lane at all"

    # And the retry now clears a budget a cold rebuild could not: the build above
    # took tens of seconds against real lanes, while a populated cache answers in
    # milliseconds, so two seconds separates the two states rather than merely
    # being small. (A millisecond would not: it expires before the task takes its
    # first step, and would pass for a cold catalog too.)
    domain_config.run_start_catalog_budget_seconds = 2.0
    try:
        warm = await _catalog_records_within_budget(app, workspace)
    finally:
        domain_config.run_start_catalog_budget_seconds = original
    assert {record.provider_id for record in warm} == {
        record.provider_id for record in records
    }
