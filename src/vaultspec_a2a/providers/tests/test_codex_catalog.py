"""Direct and installed-runtime tests for prompt-free Codex catalog discovery."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psutil
import pytest

from ...control.config import settings
from ...workspace.environment import resolve_env_vars
from .._stdio_rpc import OutputBudget
from ..codex_catalog import (
    CodexCatalogProtocolError,
    _authentication,
    _protocol_error,
    _rpc_error,
    catalog_from_app_server,
    discover_codex_catalog,
)
from ..provider_catalog import (
    MAX_CONTROLS,
    AuthenticationState,
    CatalogStatus,
    ControlKind,
    ProviderCatalogKey,
)

if TYPE_CHECKING:
    from .._json_contract import JsonObject

_KEY = ProviderCatalogKey("codex", "app-server")

_REPEATED_CURSOR_PROCESS = (
    "import json,sys;"
    "send=lambda message:print(json.dumps(message),flush=True);"
    "record=open(sys.argv[1],'a',encoding='utf-8');"
    'exec("for raw in sys.stdin:\\n'
    " record.write(raw)\\n"
    " record.flush()\\n"
    " m=json.loads(raw)\\n"
    " i=m.get('id')\\n"
    " if i is None: continue\\n"
    " method=m.get('method')\\n"
    " result={'account':{'type':'apiKey'},'requiresOpenaiAuth':True} "
    "if method=='account/read' else "
    "({'data':[],'nextCursor':'repeated'} if method=='model/list' else {})\\n"
    " send({'id':i,'result':result})\")"
)

_PROVIDER_ERROR_PROCESS = (
    "import json,sys;"
    "send=lambda message:print(json.dumps(message),flush=True);"
    'exec("for raw in sys.stdin:\\n'
    " m=json.loads(raw)\\n"
    " i=m.get('id')\\n"
    " if i is None: continue\\n"
    " if m.get('method')=='account/read':\\n"
    "  send({'id':i,'error':{'code':-32603,'message':'TOKEN=secret-value'}})\\n"
    " else:\\n"
    "  send({'id':i,'result':{}})\")"
)

_OVERSIZED_STDERR_PROCESS = (
    "import sys,time;"
    "sys.stderr.buffer.write(b'x'*1048577);"
    "sys.stderr.buffer.flush();"
    "time.sleep(30)"
)


def _model(
    value: str,
    *,
    efforts: tuple[str, ...] = ("brief", "deep"),
    service_tiers: tuple[str, ...] = ("standard", "fast"),
) -> JsonObject:
    return {
        "id": f"picker-{value}",
        "model": value,
        "displayName": value.upper(),
        "description": f"Description for {value}",
        "hidden": False,
        "isDefault": False,
        "defaultReasoningEffort": efforts[0],
        "supportedReasoningEfforts": [
            {"reasoningEffort": effort, "description": f"{effort} reasoning"}
            for effort in efforts
        ],
        "defaultServiceTier": service_tiers[0] if service_tiers else None,
        "serviceTiers": [
            {
                "id": tier,
                "name": tier.title(),
                "description": f"{tier} service",
            }
            for tier in service_tiers
        ],
    }


def test_pages_preserve_models_reasoning_efforts_and_service_tiers() -> None:
    catalog = catalog_from_app_server(
        (
            {"data": [_model("provider-model-a")], "nextCursor": "page-two"},
            {"data": [_model("provider-model-b")], "nextCursor": None},
        ),
        {"webSearch": True, "imageGeneration": False, "namespaceTools": True},
        key=_KEY,
        checked_at=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert catalog.state.status is CatalogStatus.AVAILABLE
    assert [model.provider_value for model in catalog.models] == [
        "provider-model-a",
        "provider-model-b",
    ]
    assert catalog.models[0].capabilities == ("web_search", "namespace_tools")
    assert [control.kind for control in catalog.native_controls] == [
        ControlKind.THOUGHT_LEVEL,
        ControlKind.SERVICE_TIER,
        ControlKind.THOUGHT_LEVEL,
        ControlKind.SERVICE_TIER,
    ]
    reasoning = catalog.native_controls[0]
    assert [option.provider_value for option in reasoning.options] == ["brief", "deep"]
    assert reasoning.default_option_id == reasoning.options[0].option_id
    service = catalog.native_controls[1]
    assert [option.provider_value for option in service.options] == [
        "standard",
        "fast",
    ]
    assert service.control_id != catalog.native_controls[3].control_id
    assert catalog.models[0].native_control_ids == (
        catalog.native_controls[0].control_id,
        catalog.native_controls[1].control_id,
    )
    assert catalog.models[1].native_control_ids == (
        catalog.native_controls[2].control_id,
        catalog.native_controls[3].control_id,
    )
    assert set(catalog.models[0].native_control_ids).isdisjoint(
        catalog.models[1].native_control_ids
    )


def test_deprecated_speed_tiers_are_retained_when_service_tiers_are_absent() -> None:
    model = _model("provider-model-a", service_tiers=())
    model["additionalSpeedTiers"] = ["accelerated", "maximum"]
    catalog = catalog_from_app_server(
        ({"data": [model], "nextCursor": None},),
        {"webSearch": False, "imageGeneration": False, "namespaceTools": False},
        key=_KEY,
    )
    service = catalog.native_controls[1]
    assert service.kind is ControlKind.SERVICE_TIER
    assert [option.provider_value for option in service.options] == [
        "accelerated",
        "maximum",
    ]


def test_account_read_normalizes_authentication_evidence() -> None:
    assert (
        _authentication({"account": {"type": "apiKey"}, "requiresOpenaiAuth": True})
        is AuthenticationState.AUTHENTICATED
    )
    assert (
        _authentication({"account": None, "requiresOpenaiAuth": True})
        is AuthenticationState.UNAUTHENTICATED
    )
    assert (
        _authentication({"account": None, "requiresOpenaiAuth": False})
        is AuthenticationState.NOT_APPLICABLE
    )


def test_empty_catalog_and_malformed_capability_fail_closed() -> None:
    catalog = catalog_from_app_server(
        ({"data": [], "nextCursor": None},),
        {"webSearch": False, "imageGeneration": False, "namespaceTools": False},
        key=_KEY,
    )
    assert catalog.state.status is CatalogStatus.UNAVAILABLE
    assert catalog.models == ()
    with pytest.raises(CodexCatalogProtocolError, match="must be a boolean"):
        catalog_from_app_server(
            ({"data": [_model("provider-model-a")]},),
            cast(
                "JsonObject",
                {
                    "webSearch": "yes",
                    "imageGeneration": False,
                    "namespaceTools": False,
                },
            ),
            key=_KEY,
        )


def test_duplicate_models_and_native_control_bounds_fail_closed() -> None:
    with pytest.raises(CodexCatalogProtocolError, match="duplicate model"):
        catalog_from_app_server(
            ({"data": [_model("same"), _model("same")]},),
            {"webSearch": False, "imageGeneration": False, "namespaceTools": False},
            key=_KEY,
        )
    with pytest.raises(
        CodexCatalogProtocolError, match=f"{MAX_CONTROLS} native controls"
    ):
        # Each model carries a reasoning-effort and a service-tier control, so
        # this is the smallest model count that can exceed the bound.
        overflow = MAX_CONTROLS // 2 + 1
        catalog_from_app_server(
            ({"data": [_model(f"model-{index}") for index in range(overflow)]},),
            {"webSearch": False, "imageGeneration": False, "namespaceTools": False},
            key=_KEY,
        )


def test_catalog_revision_tracks_provider_values_controls_and_capabilities() -> None:
    # Annotated rather than inferred: dict is INVARIANT in its value type, so the
    # inferred dict[str, list[JsonObject]] is not assignable to JsonObject even
    # though a list of objects is a perfectly good JsonValue. Stating the target
    # type checks the literal against it instead of against its narrowest reading.
    base_pages: tuple[JsonObject, ...] = ({"data": [_model("provider-model-a")]},)
    base = catalog_from_app_server(
        base_pages,
        {"webSearch": False, "imageGeneration": False, "namespaceTools": False},
        key=_KEY,
    )
    same = catalog_from_app_server(
        base_pages,
        {"webSearch": False, "imageGeneration": False, "namespaceTools": False},
        key=_KEY,
    )
    changed = catalog_from_app_server(
        ({"data": [_model("provider-model-a", efforts=("brief",))]},),
        {"webSearch": True, "imageGeneration": False, "namespaceTools": False},
        key=_KEY,
    )
    assert base.state.revision == same.state.revision
    assert base.state.revision != changed.state.revision


def test_provider_error_text_is_not_retained() -> None:
    secret = "credential-value-that-must-not-escape"
    error = _rpc_error(
        "model/list", {"code": -32603, "message": f"provider failed: {secret}"}
    )
    assert secret not in str(error)
    assert str(error) == "Codex model/list failed with a provider error"


def test_stdout_and_stderr_share_one_aggregate_output_budget() -> None:
    budget = OutputBudget(_protocol_error)
    budget.charge(700_000)
    budget.charge(348_576)
    with pytest.raises(CodexCatalogProtocolError) as raised:
        budget.charge(1)
    assert str(raised.value) == "Codex discovery output exceeds one MiB"


def _real_codex_inputs() -> tuple[tuple[str, ...], dict[str, str]]:
    executable = shutil.which("codex")
    if executable is None:
        pytest.fail("Codex CLI is not installed")
    workspace = Path.cwd()
    environment = resolve_env_vars(workspace)
    codex_home = settings.codex_home
    if codex_home and codex_home.strip():
        environment["CODEX_HOME"] = codex_home
    return (executable, "app-server"), environment


@pytest.mark.service
@pytest.mark.asyncio
async def test_real_codex_catalog_discovery_reaps_without_prompt() -> None:
    command, environment = _real_codex_inputs()
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}

    discovery = await discover_codex_catalog(
        command,
        env=environment,
        cwd=str(Path.cwd()),
        key=_KEY,
        metadata={"provider": "codex"},
    )

    assert discovery.authentication in {
        AuthenticationState.AUTHENTICATED,
        AuthenticationState.NOT_APPLICABLE,
    }
    assert discovery.catalog.state.status is CatalogStatus.AVAILABLE
    assert discovery.catalog.models
    descendants = [
        child for child in parent.children(recursive=True) if child.pid not in baseline
    ]
    _, alive = await asyncio.to_thread(psutil.wait_procs, descendants, timeout=10.0)
    assert not alive, [process.pid for process in alive]


@pytest.mark.service
@pytest.mark.asyncio
async def test_real_codex_catalog_discovery_reaps_when_cancelled() -> None:
    command, environment = _real_codex_inputs()
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}
    task = asyncio.create_task(
        discover_codex_catalog(
            command,
            env=environment,
            cwd=str(Path.cwd()),
            key=_KEY,
            metadata={"provider": "codex"},
        )
    )
    deadline = asyncio.get_running_loop().time() + 10.0
    observed: list[psutil.Process] = []
    while not observed and not task.done():
        observed = [
            child
            for child in parent.children(recursive=True)
            if child.pid not in baseline
        ]
        if observed or asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(0.02)
    assert observed, "real Codex discovery spawned no observable contained process"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=20.0)
    _, alive = await asyncio.to_thread(psutil.wait_procs, observed, timeout=10.0)
    assert not alive, [process.pid for process in alive]


@pytest.mark.service
@pytest.mark.asyncio
async def test_repeated_pagination_cursor_fails_closed_and_reaps(
    tmp_path: Path,
) -> None:
    environment = resolve_env_vars(Path.cwd())
    request_log = tmp_path / "malformed-cursor-requests.jsonl"
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}
    with pytest.raises(CodexCatalogProtocolError, match="repeated a cursor"):
        await discover_codex_catalog(
            (
                sys.executable,
                "-c",
                _REPEATED_CURSOR_PROCESS,
                str(request_log),
            ),
            env=environment,
            cwd=str(Path.cwd()),
            key=_KEY,
            timeout=10.0,
        )
    requests = [json.loads(line) for line in request_log.read_text().splitlines()]
    methods = [request["method"] for request in requests]
    assert methods == [
        "initialize",
        "initialized",
        "account/read",
        "model/list",
        "model/list",
    ]
    assert requests[3]["params"]["cursor"] is None
    assert requests[4]["params"]["cursor"] == "repeated"
    descendants = [
        child for child in parent.children(recursive=True) if child.pid not in baseline
    ]
    _, alive = await asyncio.to_thread(psutil.wait_procs, descendants, timeout=10.0)
    assert not alive, [process.pid for process in alive]


@pytest.mark.service
@pytest.mark.asyncio
async def test_provider_rpc_error_is_redacted_and_reaps() -> None:
    environment = resolve_env_vars(Path.cwd())
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}
    with pytest.raises(CodexCatalogProtocolError) as raised:
        await discover_codex_catalog(
            (sys.executable, "-c", _PROVIDER_ERROR_PROCESS),
            env=environment,
            cwd=str(Path.cwd()),
            key=_KEY,
            timeout=10.0,
        )
    assert "secret-value" not in str(raised.value)
    assert str(raised.value) == "Codex account/read failed with a provider error"
    descendants = [
        child for child in parent.children(recursive=True) if child.pid not in baseline
    ]
    _, alive = await asyncio.to_thread(psutil.wait_procs, descendants, timeout=10.0)
    assert not alive, [process.pid for process in alive]


@pytest.mark.service
@pytest.mark.asyncio
async def test_aggregate_output_budget_failure_reaps_process() -> None:
    environment = resolve_env_vars(Path.cwd())
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}
    with pytest.raises(CodexCatalogProtocolError, match="exceeds one MiB"):
        await discover_codex_catalog(
            (sys.executable, "-c", _OVERSIZED_STDERR_PROCESS),
            env=environment,
            cwd=str(Path.cwd()),
            key=_KEY,
            timeout=10.0,
        )
    descendants = [
        child for child in parent.children(recursive=True) if child.pid not in baseline
    ]
    _, alive = await asyncio.to_thread(psutil.wait_procs, descendants, timeout=10.0)
    assert not alive, [process.pid for process in alive]
