"""Direct and installed-runtime tests for prompt-free Kimi catalog discovery."""

from __future__ import annotations

import asyncio
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import psutil
import pytest

from ...workspace.environment import resolve_env_vars
from .._stdio_rpc import OutputBudget
from ..kimi_catalog import (
    KimiCatalogProtocolError,
    _protocol_error,
    catalog_from_provider_list,
    discover_kimi_catalog,
)
from ..provider_catalog import (
    AuthenticationState,
    CatalogStatus,
    ControlKind,
    ProviderCatalogKey,
)

if TYPE_CHECKING:
    from .._json_contract import JsonObject

_KEY = ProviderCatalogKey("kimi", "cli")

_DUAL_STREAM_OUTPUT_PROCESS = (
    "import json,os;"
    "os.write(2,b'e'*100000);"
    "os.write(1,json.dumps({'providers':{'p':{'type':'kimi','apiKey':'x'*100000}},"
    "'models':{'a':{'provider':'p','model':'wire','maxContextSize':1}}}).encode())"
)

_OVERSIZED_AGGREGATE_PROCESS = (
    "import os,time;"
    "os.write(2,b'e'*600000);"
    "os.write(1,b'{' + b' '*600000);"
    "time.sleep(30)"
)

_TIMEOUT_PROCESS = "import time;time.sleep(30)"


def _configured_result(
    *,
    wire_model: str = "wire-model-a",
    efforts: tuple[str, ...] = ("brief", "deep"),
) -> JsonObject:
    return {
        "providers": {
            "configured-provider": {
                "type": "kimi",
                "apiKey": "credential-value-that-must-not-escape",
                "baseUrl": "https://example.invalid/v1",
            }
        },
        "models": {
            "configured-alias": {
                "provider": "configured-provider",
                "model": wire_model,
                "maxContextSize": 131_072,
                "displayName": "Configured alias",
                "capabilities": ["thinking", "image_in"],
                "supportEfforts": list(efforts),
                "defaultEffort": efforts[0] if efforts else None,
                "offEffort": "off",
                "adaptiveThinking": True,
            }
        },
    }


def test_configured_alias_and_ordered_thinking_control_are_normalized() -> None:
    secret = "credential-value-that-must-not-escape"
    catalog = catalog_from_provider_list(
        _configured_result(),
        key=_KEY,
        checked_at=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert catalog.state.status is CatalogStatus.AVAILABLE
    assert len(catalog.models) == 1
    model = catalog.models[0]
    assert model.provider_value == "configured-alias"
    assert model.display_name == "Configured alias"
    assert model.capabilities == ("thinking", "image_in")
    assert len(catalog.native_controls) == 1
    control = catalog.native_controls[0]
    assert control.kind is ControlKind.THOUGHT_LEVEL
    assert [option.provider_value for option in control.options] == ["brief", "deep"]
    assert control.default_option_id == control.options[0].option_id
    assert model.native_control_ids == (control.control_id,)
    assert secret not in repr(catalog)
    assert "wire-model-a" not in repr(catalog)


def test_model_without_advertised_efforts_gets_no_invented_control() -> None:
    result = _configured_result(efforts=())
    models = result.get("models")
    assert isinstance(models, dict)
    model = models.get("configured-alias")
    assert isinstance(model, dict)
    model.pop("defaultEffort")
    catalog = catalog_from_provider_list(result, key=_KEY)
    assert catalog.native_controls == ()
    assert catalog.models[0].native_control_ids == ()


def test_empty_configured_lane_is_truthfully_unavailable() -> None:
    catalog = catalog_from_provider_list(
        {"providers": {}, "models": {}},
        key=_KEY,
    )
    assert catalog.state.status is CatalogStatus.UNAVAILABLE
    assert catalog.models == ()
    assert catalog.state.reason == "Kimi CLI has no configured model aliases"


def test_unknown_provider_and_duplicate_efforts_fail_closed() -> None:
    unknown = _configured_result()
    unknown["providers"] = {}
    with pytest.raises(KimiCatalogProtocolError, match="unknown provider"):
        catalog_from_provider_list(unknown, key=_KEY)

    malformed_provider = _configured_result()
    malformed_provider["providers"] = {"configured-provider": None}
    with pytest.raises(KimiCatalogProtocolError, match="must be an object"):
        catalog_from_provider_list(malformed_provider, key=_KEY)

    duplicate = _configured_result(efforts=("same", "same"))
    with pytest.raises(KimiCatalogProtocolError, match="duplicate values"):
        catalog_from_provider_list(duplicate, key=_KEY)


def test_native_control_bound_fails_before_normalized_contract_construction() -> None:
    result = _configured_result()
    models = result.get("models")
    assert isinstance(models, dict)
    template = models.get("configured-alias")
    assert isinstance(template, dict)
    result["models"] = {
        f"alias-{index}": {**template, "model": f"wire-{index}"} for index in range(33)
    }
    with pytest.raises(KimiCatalogProtocolError, match="32 native controls"):
        catalog_from_provider_list(result, key=_KEY)


def test_revision_tracks_wire_target_and_effort_choices() -> None:
    base = catalog_from_provider_list(_configured_result(), key=_KEY)
    same = catalog_from_provider_list(_configured_result(), key=_KEY)
    changed_wire = catalog_from_provider_list(
        _configured_result(wire_model="wire-model-b"), key=_KEY
    )
    changed_efforts = catalog_from_provider_list(
        _configured_result(efforts=("brief",)), key=_KEY
    )
    assert base.state.revision == same.state.revision
    assert base.state.revision != changed_wire.state.revision
    assert base.state.revision != changed_efforts.state.revision


def test_stdout_and_stderr_share_one_aggregate_output_budget() -> None:
    budget = OutputBudget(_protocol_error)
    budget.charge(700_000)
    budget.charge(348_576)
    with pytest.raises(KimiCatalogProtocolError) as raised:
        budget.charge(1)
    assert str(raised.value) == "Kimi discovery output exceeds one MiB"


def _installed_kimi() -> str:
    executable = shutil.which("kimi")
    if executable is None:
        pytest.fail("Kimi CLI is not installed")
    return executable


def _runtime_environment() -> dict[str, str]:
    """Use the installed CLI's actual configuration without fabricating credentials."""
    return resolve_env_vars(Path.cwd())


def _configured_runtime_environment() -> tuple[dict[str, str], str, str]:
    """Configure the installed CLI's documented temporary provider lane."""
    environment = _runtime_environment()
    secret = "catalog-probe-credential"
    model = "catalog-probe-model"
    environment.update(
        {
            "KIMI_MODEL_NAME": model,
            "KIMI_MODEL_API_KEY": secret,
            "KIMI_MODEL_BASE_URL": "https://example.invalid/v1",
            "KIMI_MODEL_MAX_CONTEXT_SIZE": "131072",
            "KIMI_MODEL_CAPABILITIES": "thinking,image_in",
        }
    )
    return environment, secret, model


@pytest.mark.service
@pytest.mark.asyncio
async def test_large_real_process_output_drains_concurrently_and_reaps() -> None:
    environment = resolve_env_vars(Path.cwd())
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}
    discovery = await discover_kimi_catalog(
        (sys.executable, "-c", _DUAL_STREAM_OUTPUT_PROCESS),
        env=environment,
        cwd=str(Path.cwd()),
        key=_KEY,
        timeout=10.0,
    )
    assert discovery.catalog.state.status is CatalogStatus.AVAILABLE
    assert discovery.catalog.models[0].provider_value == "a"
    descendants = [
        child for child in parent.children(recursive=True) if child.pid not in baseline
    ]
    _, alive = await asyncio.to_thread(psutil.wait_procs, descendants, timeout=10.0)
    assert not alive, [process.pid for process in alive]


@pytest.mark.service
@pytest.mark.asyncio
async def test_real_process_aggregate_output_breach_is_static_and_reaps() -> None:
    environment = resolve_env_vars(Path.cwd())
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}
    with pytest.raises(KimiCatalogProtocolError) as raised:
        await discover_kimi_catalog(
            (sys.executable, "-c", _OVERSIZED_AGGREGATE_PROCESS),
            env=environment,
            cwd=str(Path.cwd()),
            key=_KEY,
            timeout=10.0,
        )
    assert str(raised.value) == "Kimi discovery output exceeds one MiB"
    descendants = [
        child for child in parent.children(recursive=True) if child.pid not in baseline
    ]
    _, alive = await asyncio.to_thread(psutil.wait_procs, descendants, timeout=10.0)
    assert not alive, [process.pid for process in alive]


@pytest.mark.service
@pytest.mark.asyncio
async def test_real_process_timeout_reaps() -> None:
    environment = resolve_env_vars(Path.cwd())
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}
    with pytest.raises(TimeoutError):
        await discover_kimi_catalog(
            (sys.executable, "-c", _TIMEOUT_PROCESS),
            env=environment,
            cwd=str(Path.cwd()),
            key=_KEY,
            timeout=0.1,
        )
    descendants = [
        child for child in parent.children(recursive=True) if child.pid not in baseline
    ]
    _, alive = await asyncio.to_thread(psutil.wait_procs, descendants, timeout=10.0)
    assert not alive, [process.pid for process in alive]


@pytest.mark.service
@pytest.mark.asyncio
async def test_installed_kimi_configured_lane_enumerates_without_prompt() -> None:
    executable = _installed_kimi()
    environment, secret, model = _configured_runtime_environment()
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}

    discovery = await discover_kimi_catalog(
        (executable,),
        env=environment,
        cwd=str(Path.cwd()),
        key=_KEY,
        metadata={"provider": "kimi"},
    )

    assert discovery.authentication is AuthenticationState.UNKNOWN
    assert discovery.catalog.state.status is CatalogStatus.AVAILABLE
    assert len(discovery.catalog.models) == 1
    assert discovery.catalog.models[0].provider_value == "__kimi_env_model__"
    assert discovery.catalog.models[0].capabilities == ("thinking", "image_in")
    assert secret not in repr(discovery)
    assert model not in repr(discovery)
    descendants = [
        child for child in parent.children(recursive=True) if child.pid not in baseline
    ]
    _, alive = await asyncio.to_thread(psutil.wait_procs, descendants, timeout=10.0)
    assert not alive, [process.pid for process in alive]


@pytest.mark.service
@pytest.mark.asyncio
async def test_installed_kimi_unconfigured_lane_is_truthfully_unavailable() -> None:
    executable = _installed_kimi()
    environment = _runtime_environment()
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}

    discovery = await discover_kimi_catalog(
        (executable,),
        env=environment,
        cwd=str(Path.cwd()),
        key=_KEY,
        metadata={"provider": "kimi"},
    )

    assert discovery.authentication is AuthenticationState.UNKNOWN
    assert discovery.catalog.state.status is CatalogStatus.UNAVAILABLE
    assert discovery.catalog.models == ()
    assert discovery.catalog.state.reason == "Kimi CLI has no configured model aliases"
    descendants = [
        child for child in parent.children(recursive=True) if child.pid not in baseline
    ]
    _, alive = await asyncio.to_thread(psutil.wait_procs, descendants, timeout=10.0)
    assert not alive, [process.pid for process in alive]


@pytest.mark.service
@pytest.mark.asyncio
async def test_installed_kimi_failure_is_static_and_reaps() -> None:
    executable = _installed_kimi()
    environment = _runtime_environment()
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}

    with pytest.raises(KimiCatalogProtocolError) as raised:
        await discover_kimi_catalog(
            (executable, "--definitely-invalid-option"),
            env=environment,
            cwd=str(Path.cwd()),
            key=_KEY,
            metadata={"provider": "kimi"},
        )
    assert str(raised.value) == "Kimi provider-list discovery failed"
    descendants = [
        child for child in parent.children(recursive=True) if child.pid not in baseline
    ]
    _, alive = await asyncio.to_thread(psutil.wait_procs, descendants, timeout=10.0)
    assert not alive, [process.pid for process in alive]


@pytest.mark.service
@pytest.mark.asyncio
async def test_installed_kimi_discovery_reaps_when_cancelled() -> None:
    executable = _installed_kimi()
    environment = _runtime_environment()
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}
    task = asyncio.create_task(
        discover_kimi_catalog(
            (executable,),
            env=environment,
            cwd=str(Path.cwd()),
            key=_KEY,
            metadata={"provider": "kimi"},
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
    assert observed, "installed Kimi discovery spawned no observable contained process"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=20.0)
    _, alive = await asyncio.to_thread(psutil.wait_procs, observed, timeout=10.0)
    assert not alive, [process.pid for process in alive]
