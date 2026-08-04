"""Permanent deterministic completion proof for the real gateway-owned worker.

The scenario uses the bundled ``vaultspec-adr-research-deterministic`` preset.
Its model is selected by the production :class:`ProviderFactory`; the gateway,
worker process, dispatch transport, graph, checkpoint store, and history read
remain real.  Unlike the tape-backed completion test, there is no optional
network backend and no skip path: a missing scenario, failed run, history, or
emitted review artifact is a test failure.

The automated lane writes a run-bound review bundle containing the authored
output and durable execution evidence.  It deliberately records the manual
review as pending: approving that bundle belongs to the separate S31 step.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, cast

import pytest

from ...authoring import AuthoringClient, AuthoringResponse, Denial, mint_actor_token
from ...authoring.discovery import (
    SERVICE_JSON_ENV,
    EngineEndpoint,
)
from ...control.run_start_policy import required_role_ids
from ...team.team_config import load_team_config
from ...thread.enums import TERMINAL_STATUS_VALUES
from .. import certified_gateway
from .conftest import wait_for_run_status

_BUNDLE_ROOT_ENV = "VAULTSPEC_ACCEPTANCE_BUNDLE_DIR"
_SCENARIO_PATH = (
    Path(__file__).resolve().parent
    / "artifacts"
    / "deterministic-completion-scenario.json"
)
_DURABLE_BUNDLE_ROOT = _SCENARIO_PATH.parent / "runs"


def _required_object(value: object, *, at: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AssertionError(f"{at} must be a JSON object")
    return cast("dict[str, object]", value)


def _required_text(value: object, *, at: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssertionError(f"{at} must be non-empty text")
    return value


def _read_scenario() -> dict[str, object]:
    """Load the committed scenario contract or fail before any run is started."""
    try:
        raw = json.loads(_SCENARIO_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssertionError(
            "required deterministic completion scenario is unreadable: "
            f"{_SCENARIO_PATH}"
        ) from exc

    scenario = _required_object(raw, at=f"scenario {_SCENARIO_PATH}")
    for key in ("scenario_id", "team_preset", "feature_tag", "message"):
        _required_text(scenario.get(key), at=f"scenario {_SCENARIO_PATH}.{key}")

    authored_output = _required_object(
        scenario.get("authored_output"), at=f"scenario {_SCENARIO_PATH}.authored_output"
    )
    for key in ("agent_id", "content"):
        _required_text(
            authored_output.get(key),
            at=f"scenario {_SCENARIO_PATH}.authored_output.{key}",
        )
    return scenario


def _digest(path: Path) -> str:
    """Return the content identity stored in the review-bundle manifest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _bundle_root() -> Path:
    """Return the required durable root for committed review evidence."""
    configured = os.environ.get(_BUNDLE_ROOT_ENV)
    assert configured, (
        "deterministic completion requires VAULTSPEC_ACCEPTANCE_BUNDLE_DIR; "
        "an ephemeral test-only review bundle is not S05 evidence"
    )
    root = Path(configured).resolve()
    assert root == _DURABLE_BUNDLE_ROOT.resolve(), (
        "deterministic completion review evidence must be emitted under the "
        f"committed artifact root {_DURABLE_BUNDLE_ROOT}, not {root}"
    )
    assert root.is_dir(), f"required durable review-bundle root is absent: {root}"
    return root


def _emit_review_bundle(
    *,
    bundle_root: Path,
    scenario: dict[str, object],
    run_id: str,
    authored_output: str,
    materialized: dict[str, Path],
    status: dict[str, Any],
    history: dict[str, Any],
) -> Path:
    """Write and self-verify the automated evidence awaiting separate review."""
    scenario_id = str(scenario["scenario_id"])
    bundle = bundle_root / scenario_id / run_id
    bundle.mkdir(parents=True, exist_ok=False)

    scenario_copy = bundle / "scenario.json"
    authored_path = bundle / "scripted-adr-output.md"
    evidence_path = bundle / "execution-evidence.json"
    manifest_path = bundle / "manifest.json"

    _write_json(scenario_copy, scenario)
    authored_path.write_text(authored_output, encoding="utf-8")
    materialized_paths: dict[str, Path] = {}
    for kind, source in materialized.items():
        copied = bundle / f"authored-{kind}.md"
        copied.write_bytes(source.read_bytes())
        materialized_paths[kind] = copied
    _write_json(
        evidence_path,
        {
            "scenario_id": scenario_id,
            "run_id": run_id,
            "terminal_status": status,
            "run_history": history,
        },
    )
    artifacts = {
        scenario_copy.name: _digest(scenario_copy),
        authored_path.name: _digest(authored_path),
        evidence_path.name: _digest(evidence_path),
    }
    artifacts.update({path.name: _digest(path) for path in materialized_paths.values()})
    _write_json(
        manifest_path,
        {
            "bundle_id": f"{scenario_id}:{run_id}",
            "scenario_id": scenario_id,
            "run_id": run_id,
            "review": {"status": "pending", "required_step": "W01.P02.S31"},
            "artifacts": artifacts,
        },
    )

    manifest = _required_object(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        at=f"review bundle manifest {manifest_path}",
    )
    assert _required_text(manifest.get("bundle_id"), at="manifest.bundle_id") == (
        f"{scenario_id}:{run_id}"
    )
    review = _required_object(manifest.get("review"), at="manifest.review")
    assert review == {
        "status": "pending",
        "required_step": "W01.P02.S31",
    }
    artifacts = _required_object(manifest.get("artifacts"), at="manifest.artifacts")
    for name, identity in artifacts.items():
        assert isinstance(name, str)
        assert isinstance(identity, str)
        artifact = bundle / name
        assert artifact.is_file(), f"required review artifact is absent: {artifact}"
        assert _digest(artifact) == identity, f"review artifact changed: {artifact}"
    assert authored_path.read_text(encoding="utf-8") == authored_output
    return bundle


async def _mint_token(client: AuthoringClient, *, actor_id: str, kind: str) -> str:
    minted = await mint_actor_token(client, actor_id=actor_id, kind=kind)
    assert isinstance(minted, AuthoringResponse), f"actor-token mint denied: {minted}"
    token = minted.data.get("raw_token")
    assert isinstance(token, str) and token, "actor-token receipt carried no token"
    return token


async def _set_autonomous_mode(client: AuthoringClient, reviewer_token: str) -> None:
    result = await client.post_command(
        "/v1/mode",
        "set_operation_mode",
        {"mode": "autonomous"},
        idempotency_key="idk-s05-deterministic-mode",
        actor_token=reviewer_token,
    )
    if isinstance(result, Denial):
        raise AssertionError(
            f"deterministic completion mode change denied: {result.denial_kind}: "
            f"{result.reason}"
        )
    assert result.data.get("status") in {"recorded", "replayed"}, result.data
    assert result.data.get("mode") == "autonomous", result.data


async def _await_materialized_documents(
    vault_root: Path, feature_tag: str, *, timeout: float
) -> dict[str, Path]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        materialized: dict[str, Path] = {}
        for kind in ("research", "adr"):
            matches = sorted((vault_root / kind).glob(f"*{feature_tag}*.md"))
            if len(matches) == 1 and matches[0].is_file() and matches[0].stat().st_size:
                materialized[kind] = matches[0]
        if len(materialized) == 2:
            return materialized
        await asyncio.sleep(0.5)
    raise AssertionError(
        f"deterministic completion did not materialize research and ADR documents "
        f"for feature {feature_tag!r} under {vault_root}"
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_deterministic_completion_emits_a_run_bound_review_bundle(
    tmp_path: Path,
    live_engine: EngineEndpoint,
) -> None:
    """A real deterministic run completes and emits exact, bound review evidence."""
    scenario = _read_scenario()
    preset = _required_text(scenario.get("team_preset"), at="scenario.team_preset")
    run_id = f"deterministic-completion-{uuid.uuid4().hex}"
    feature_tag = f"s05-deterministic-{run_id.rsplit('-', 1)[-1]}"
    team_config = load_team_config(preset)
    roles = required_role_ids(team_config)
    assert roles, f"deterministic preset {preset!r} declares no required roles"
    # Resolved through the ONE external-prerequisite rule rather than a local
    # probe. An absent cross-repo engine is reported as a skip naming the runbook
    # line, and becomes a hard failure for a caller that declared `loopback-stack`
    # present - which is how this suite keeps "no engine is a failure, not a
    # skip" without a red gate that says nothing about THIS repository's health.
    endpoint = live_engine
    service_json = os.environ.get(SERVICE_JSON_ENV)
    assert service_json, (
        f"deterministic completion requires {SERVICE_JSON_ENV} to bind its "
        "materialized artifacts to the engine workspace"
    )
    vault_root = Path(service_json).parents[2]
    assert vault_root.is_dir(), f"engine vault root is absent: {vault_root}"

    async with AuthoringClient(endpoint.base_url, endpoint.bearer_token) as authoring:
        tokens = {
            role: await _mint_token(
                authoring, actor_id=f"agent:{run_id}:{role}", kind="agent"
            )
            for role in roles
        }
        reviewer_token = await _mint_token(
            authoring, actor_id=f"reviewer:{run_id}", kind="human"
        )
        await _set_autonomous_mode(authoring, reviewer_token)

        with certified_gateway(
            tmp_path, VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED="true"
        ) as gateway:
            started = gateway.client(timeout=90.0).post(
                "/v1/runs",
                json={
                    "team_preset": preset,
                    "stage": "start",
                    "run_id": run_id,
                    "message": _required_text(
                        scenario.get("message"), at="scenario.message"
                    ),
                    "profile_id": "team-defaults",
                    "feature_tag": feature_tag,
                    "metadata": {
                        "workspace_root": str(vault_root.parent),
                        "feature_tag": feature_tag,
                        "nickname": run_id,
                    },
                    "autonomous": True,
                    "actor_tokens": {
                        "tokens": tokens,
                        "engine_bearer": endpoint.bearer_token,
                    },
                },
            )
            assert started.status_code == 201, started.text

            materialized = await _await_materialized_documents(
                vault_root, feature_tag, timeout=180.0
            )
            terminal = await asyncio.to_thread(
                wait_for_run_status,
                gateway,
                run_id,
                lambda body: body.get("status") in TERMINAL_STATUS_VALUES,
                timeout=180.0,
            )
            assert terminal["status"] == "completed", terminal

            history_response = gateway.thread_state(run_id)
            assert history_response.status_code == 200, history_response.text
    history = _required_object(history_response.json(), at="run history")

    state = _required_object(history.get("state"), at=f"run history state: {history}")
    assert state.get("snapshot_complete") is True, state
    assert state.get("repair_status") == "healthy", state
    assert state.get("execution_readiness") == "healthy", state
    assert state.get("degraded_reasons") == [], state
    messages = state.get("messages")
    assert isinstance(messages, list), f"run history has no messages: {history}"
    typed_messages = cast("list[object]", messages)
    expected = _required_object(
        scenario.get("authored_output"), at="scenario.authored_output"
    )
    expected_agent = _required_text(
        expected.get("agent_id"), at="authored_output.agent_id"
    )
    expected_content = _required_text(
        expected.get("content"), at="authored_output.content"
    )
    turns: list[dict[str, object]] = []
    for message in typed_messages:
        if not isinstance(message, dict):
            continue
        turn = cast("dict[str, object]", message)
        if turn.get("role") == "assistant" and turn.get("agent_id") == expected_agent:
            turns.append(turn)
    assert turns, (
        f"completed run {run_id} has no authored output from {expected_agent!r}; "
        f"history={history}"
    )
    content = _required_text(turns[-1].get("content"), at="authored output content")
    assert content == expected_content, (
        f"run {run_id} authored unexpected scripted content: {content!r}"
    )

    bundle = _emit_review_bundle(
        bundle_root=_bundle_root(),
        scenario=scenario,
        run_id=run_id,
        authored_output=content,
        materialized=materialized,
        status=terminal,
        history=history,
    )
    assert bundle.is_dir(), f"review bundle was not emitted: {bundle}"
