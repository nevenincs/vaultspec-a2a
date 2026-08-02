"""Live proof that a REAL provider refusal surfaces its typed condition end to end.

Every other test in this campaign proves one hop. This one proves the chain: a
served lane refuses real work, the lane resolves a condition from the
discriminator the provider put on the wire, ingest stashes it, the settle path
forwards it on the terminal, the gateway persists it, and a client that attached
NO stream reads it back off ``run-status``.

Run-status is the assertion surface on purpose. The error frame carrying the
condition is droppable, so asserting on the frame would prove the channel a
reloading client cannot rely on. The value only counts here if it survived the
durable write and the projection, which is exactly what a client reloading onto
a finished run depends on.

**The provocation is a parameter, not a constant.** The operator arms the stack
so a real refusal will happen and DECLARES which condition to expect; this module
then proves the declared condition reached run-status. That shape is deliberate:
refusals are not equally summonable - a throttle or an exhausted window arrives
when the account says so, not when a test asks - so welding this proof to one
provocation would make it undrivable whenever that particular one is out of
reach. What is asserted is the campaign's actual claim, which is about the chain
rather than about any single member of the vocabulary.

A NOTE ON ONE PROVOCATION THAT DOES NOT WORK, recorded so it is not rediscovered.
Swapping in a deliberately invalid bearer is the proven recipe at the MODEL level,
because a directly constructed model never consults the catalog. It does not lift
to a run started through the gateway. The provider catalog authenticates first -
the ACP lane opens a real ``session/new`` during discovery - so an invalid
credential yields an unavailable catalog with no entries at all. A run cannot then
be created, because the required selection names a ``catalog_revision`` and an
``entry_id`` that do not exist, and the lane is not selectable. The run is refused
BEFORE admission, which is correct behaviour and is not a provider condition. A
usable provocation must therefore be one the credential survives: a genuinely
throttled or exhausted account, or a transport severed after discovery.

Arm and run (the stack must already be serving, and the declared condition must be
one the armed lane will really produce):

    VAULTSPEC_PROVIDER_CONDITION_EXPECT=throttled \\
        uv run --no-sync pytest -m service \\
        src/vaultspec_a2a/service_tests/test_provider_condition_live.py

Service-marked, so deselected from the default suite. With no stack, or with no
declaration, it SKIPS naming what is missing - an unproven chain is reported as
unproven, never as proven.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import TYPE_CHECKING

import httpx
import pytest

from ..api.schemas.gateway import ProviderCatalogSelection
from ..providers.conditions import ProviderCondition
from .test_pw7_acceptance import _GATEWAY_AUTH_HEADERS, _reachable_stack

if TYPE_CHECKING:
    from ..conftest import ExternalPrerequisiteRule

JsonObject = dict[str, object]

#: Names the condition the operator has armed the stack to produce. Its presence
#: is also the consent to spend a real credential: without it this module never
#: starts a run, so pointing the default suite at a healthy stack cannot burn
#: quota and cannot report a confusing failure for a run that simply succeeded.
_EXPECT_ENV = "VAULTSPEC_PROVIDER_CONDITION_EXPECT"

#: The preset the provocation rides. A coding topology deliberately: it authors no
#: document, so the run needs no engine session and no actor tokens, and the only
#: thing standing between run-start and a provider turn is the provider itself.
_PROBE_PRESET = "vaultspec-solo-coder"

#: A refusal does not arrive promptly. The lane treats several conditions as
#: retryable and exhausts a backoff schedule first - a rejected credential took
#: just under four minutes when this campaign first measured it, and the retry
#: classifier has since been bound to MORE conditions, so the wait can only have
#: grown. Generous enough that a real refusal is never cut short, bounded so a
#: genuine hang fails loud instead of parking forever.
_TERMINAL_DEADLINE_SECONDS = 900.0

#: How often run-status is asked whether the run has gone terminal.
_POLL_SECONDS = 10.0


def _declared_expectation() -> ProviderCondition | None:
    """Read the armed condition, refusing a value outside the vocabulary.

    A typo must not degrade into a silent skip - that is how a proof comes to be
    reported as unavailable forever - so an unset variable skips while a set but
    unrecognised one fails loud.
    """
    raw = (os.environ.get(_EXPECT_ENV) or "").strip()
    if not raw:
        return None
    try:
        return ProviderCondition(raw)
    except ValueError:
        pytest.fail(
            f"{_EXPECT_ENV}={raw!r} is not a member of the provider condition "
            f"vocabulary; expected one of "
            f"{sorted(member.value for member in ProviderCondition)}"
        )


def _selection_from_catalog(catalog: JsonObject) -> ProviderCatalogSelection | None:
    """Build a schema-valid selection from the first selectable served lane.

    Read from the catalog the gateway actually served rather than assembled from
    constants: a selection names a ``catalog_revision`` and an ``entry_id`` that
    have to revalidate against the live workspace catalog at admission, so a
    hand-written one would be refused the moment the catalog turned over.
    """
    providers = catalog.get("providers")
    if not isinstance(providers, list):
        return None
    for record in providers:
        if not isinstance(record, dict):
            continue
        health = record.get("health")
        lane = record.get("catalog")
        if not isinstance(health, dict) or not isinstance(lane, dict):
            continue
        if health.get("selectable") is not True:
            continue
        state = lane.get("state")
        models = lane.get("models")
        if not isinstance(state, dict) or not isinstance(models, list) or not models:
            continue
        revision = state.get("revision")
        entry = models[0]
        if not isinstance(revision, str) or not isinstance(entry, dict):
            continue
        entry_id = entry.get("entry_id")
        provider_id = record.get("provider_id")
        execution_mode = record.get("execution_mode")
        if not (
            isinstance(entry_id, str)
            and isinstance(provider_id, str)
            and isinstance(execution_mode, str)
        ):
            continue
        return ProviderCatalogSelection(
            schema_version=1,
            provider_id=provider_id,
            execution_mode=execution_mode,
            catalog_revision=revision,
            entry_id=entry_id,
        )
    return None


@pytest.mark.service
@pytest.mark.resource("loopback-stack")
@pytest.mark.asyncio
@pytest.mark.timeout(_TERMINAL_DEADLINE_SECONDS + 300.0)
async def test_a_real_provider_refusal_reaches_run_status_as_a_typed_condition(
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """The whole chain, asserted where a reloading client actually reads.

    No stream is ever attached. The condition is read from ``run-status`` alone,
    so a value that reached only the droppable frame fails this test.
    """
    expected = _declared_expectation()
    if expected is None:
        pytest.skip(
            f"{_EXPECT_ENV} is not set, so no lane is armed to refuse work and no "
            "real provider condition can be observed. This is a truthful skip "
            "naming the missing prerequisite: the chain is unproven, not proven"
        )

    stack = _reachable_stack()
    if stack is None:
        external_prerequisite.absent("loopback-stack")
    gateway_url, _engine_base_url, _engine_bearer, vault_root = stack
    workspace_root = str(vault_root.parent)

    run_id = f"provider-condition-{uuid.uuid4().hex[:12]}"

    async with httpx.AsyncClient(headers=_GATEWAY_AUTH_HEADERS) as hc:
        catalog_resp = await hc.get(
            f"{gateway_url}/v1/provider-catalog",
            params={"workspace_root": workspace_root},
            timeout=120.0,
        )
        assert catalog_resp.status_code == 200, (
            f"the served provider catalog is unavailable ({catalog_resp.status_code}): "
            f"{catalog_resp.text}. Without it no run can name a selection"
        )
        selection = _selection_from_catalog(catalog_resp.json())
        assert selection is not None, (
            "no served lane is selectable with at least one catalog entry, so no "
            "run can be started at all. Note that a lane armed by BREAKING its "
            "credential lands here: catalog discovery authenticates, so an invalid "
            "credential empties the catalog and the run is refused before "
            "admission - which is not a provider condition. Arm a refusal the "
            "credential survives instead"
        )

        start = await hc.post(
            f"{gateway_url}/v1/runs",
            json={
                "team_preset": _PROBE_PRESET,
                "message": "Reply with the single word: pong",
                "run_id": run_id,
                "selection": selection.model_dump(mode="json"),
                "metadata": {"workspace_root": workspace_root, "nickname": run_id},
            },
            timeout=120.0,
        )
        assert start.status_code == 201, (
            f"run-start expected 201, got {start.status_code}: {start.text}"
        )

        status: JsonObject = {}
        deadline = time.monotonic() + _TERMINAL_DEADLINE_SECONDS
        while time.monotonic() < deadline:
            resp = await hc.get(f"{gateway_url}/v1/runs/{run_id}", timeout=30.0)
            resp.raise_for_status()
            status = resp.json()
            if status.get("status") in {"failed", "completed", "cancelled"}:
                break
            await asyncio.sleep(_POLL_SECONDS)

    observed_status = status.get("status")
    assert observed_status is not None, (
        f"run {run_id} never reached a terminal state within "
        f"{_TERMINAL_DEADLINE_SECONDS}s; the chain cannot be observed"
    )
    assert observed_status == "failed", (
        f"run {run_id} ended {observed_status!r} rather than failing, so the armed "
        f"lane did not refuse work and there is no condition to prove. Reported "
        f"reason: {status.get('failure_reason')!r}"
    )

    condition = status.get("provider_condition")
    assert isinstance(condition, str) and condition, (
        f"run {run_id} failed but run-status carries NO provider condition "
        f"({condition!r}). A failed run without one is the invariant violation the "
        f"governing decision forbids. Reported reason: "
        f"{status.get('failure_reason')!r}"
    )
    assert condition in {member.value for member in ProviderCondition}, (
        f"run-status served provider condition {condition!r}, which is outside the "
        f"closed vocabulary this contract shares with the consuming repository"
    )
    assert condition == expected.value, (
        f"the armed lane was declared to produce {expected.value!r} but run-status "
        f"served {condition!r}. Reported reason: {status.get('failure_reason')!r}"
    )


def test_a_declared_condition_outside_the_vocabulary_fails_rather_than_skips() -> None:
    """Stack-free guard: a typo in the arming variable must not read as unarmed.

    The skip branch is how this module reports an unproven chain. If a misspelled
    condition fell through it, an operator who believed they had armed the proof
    would be told it was simply unavailable, and the chain would sit unproven
    while appearing merely un-run.
    """
    previous = os.environ.get(_EXPECT_ENV)
    os.environ[_EXPECT_ENV] = "not-a-real-condition"
    try:
        # ``pytest.fail`` raises ``Failed``, which descends from ``BaseException``
        # rather than ``Exception``, so the outcome type is named explicitly; a
        # plain ``Exception`` here would not catch it and the guard would pass
        # for the wrong reason.
        with pytest.raises(
            pytest.fail.Exception, match="not a member of the provider condition"
        ):
            _declared_expectation()
    finally:
        if previous is None:
            os.environ.pop(_EXPECT_ENV, None)
        else:
            os.environ[_EXPECT_ENV] = previous


def test_every_vocabulary_member_can_be_armed() -> None:
    """Stack-free guard: the arming variable spans the whole closed vocabulary.

    Enumerated from the production enum rather than a hand-copied list, so a
    member added later is armable without anyone remembering to widen a parser
    here. A refusal this module could not be pointed at would be a member the
    chain could never be proven for.
    """
    previous = os.environ.get(_EXPECT_ENV)
    try:
        for member in ProviderCondition:
            os.environ[_EXPECT_ENV] = member.value
            assert _declared_expectation() is member
    finally:
        if previous is None:
            os.environ.pop(_EXPECT_ENV, None)
        else:
            os.environ[_EXPECT_ENV] = previous


def test_an_unarmed_environment_reports_unproven_rather_than_expecting_anything() -> (
    None
):
    """Stack-free guard: absent arming yields no expectation, so no run starts."""
    previous = os.environ.get(_EXPECT_ENV)
    os.environ.pop(_EXPECT_ENV, None)
    try:
        assert _declared_expectation() is None
    finally:
        if previous is not None:
            os.environ[_EXPECT_ENV] = previous


def test_a_selection_is_built_only_from_a_selectable_lane_with_entries() -> None:
    """Stack-free guard: the request body is valid against the CURRENT run schema.

    Two things are pinned. A lane that is not selectable, or that serves no
    catalog entry, yields no selection - which is what stops this module posting
    a run that admission would refuse for a stale or absent reference. And the
    selection it does build validates as the production model, so a run-start
    body assembled here cannot drift from the schema the gateway enforces.
    """
    unusable: JsonObject = {
        "providers": [
            {  # refuses work but is not selectable
                "provider_id": "p1",
                "execution_mode": "m1",
                "health": {"selectable": False},
                "catalog": {
                    "state": {"revision": "r1"},
                    "models": [{"entry_id": "e1"}],
                },
            },
            {  # selectable but serves no entry to name
                "provider_id": "p2",
                "execution_mode": "m2",
                "health": {"selectable": True},
                "catalog": {"state": {"revision": "r2"}, "models": []},
            },
        ]
    }
    assert _selection_from_catalog(unusable) is None

    usable: JsonObject = {
        "providers": [
            {
                "provider_id": "p3",
                "execution_mode": "m3",
                "health": {"selectable": True},
                "catalog": {
                    "state": {"revision": "r3"},
                    "models": [{"entry_id": "e3"}],
                },
            }
        ]
    }
    selection = _selection_from_catalog(usable)
    assert selection is not None
    assert selection.catalog_revision == "r3"
    assert selection.entry_id == "e3"
    assert ProviderCatalogSelection.model_validate(selection.model_dump()) == selection
