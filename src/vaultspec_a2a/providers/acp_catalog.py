"""Prompt-free ACP provider catalog discovery.

Discovery performs only the ACP ``initialize`` and ``session/new`` handshake,
normalizes provider-advertised model/config choices, and always reaps the
contained subprocess. It never sends ``session/prompt`` and never logs or
returns environment values.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Mapping

from ._acp_auth import is_auth_required_error
from ._cleanup import CleanupStep, run_independent_cleanups
from ._json_contract import JsonObject, JsonValue
from ._stdio_rpc import OutputBudget, cancel_task, drain_stderr, read_response
from ._subprocess import kill_process_tree, spawn_acp_process
from .acp_exceptions import AcpErrorCode, AcpSessionError
from .provider_catalog import (
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    ControlKind,
    ModelCatalogEntry,
    NativeControl,
    NativeControlOption,
    ProviderCatalog,
    ProviderCatalogKey,
)

__all__ = [
    "AcpCatalogDiscovery",
    "AcpCatalogProtocolError",
    "catalog_from_session_result",
    "discover_acp_catalog",
]

_MAX_FRAME_BYTES: Final = 1_048_576
_MAX_FRAMES: Final = 64
_MAX_MODELS: Final = 256
_MAX_CONTROLS: Final = 32
_MAX_OPTIONS: Final = 128
_CATALOG_TTL: Final = timedelta(minutes=5)
_SUPPORTED_CONTROL_CATEGORIES: Final = frozenset({"thought_level", "model_config"})
_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class AcpCatalogProtocolError(AcpSessionError):
    """The ACP discovery surface was malformed or exceeded a safety bound."""


class _AcpCatalogAuthenticationRequiredError(AcpSessionError):
    """Internal signal used to return factual unauthenticated evidence."""


@dataclass(frozen=True, slots=True)
class AcpCatalogDiscovery:
    """Prompt-free catalog result plus authentication evidence."""

    catalog: ProviderCatalog
    authentication: AuthenticationState


def _protocol_error(message: str) -> AcpCatalogProtocolError:
    """Raise ACP's own dialect of a discovery protocol refusal."""
    return AcpCatalogProtocolError(f"ACP {message}", code=AcpErrorCode.INTERNAL_ERROR)


def _rpc_error(method: str, error: JsonValue) -> AcpSessionError:
    """Classify an ACP failure without retaining provider-controlled text."""
    detail = error if isinstance(error, dict) else {}
    code = detail.get("code")
    safe_code = (
        code
        if isinstance(code, int) and not isinstance(code, bool)
        else AcpErrorCode.INTERNAL_ERROR
    )
    if is_auth_required_error(error):
        return _AcpCatalogAuthenticationRequiredError(
            f"ACP {method} requires authentication",
            code=(
                safe_code
                if safe_code != AcpErrorCode.INTERNAL_ERROR
                else AcpErrorCode.UNAUTHENTICATED
            ),
        )
    return AcpSessionError(
        f"ACP {method} failed with a provider error",
        code=safe_code,
    )


def _unauthenticated_discovery(key: ProviderCatalogKey) -> AcpCatalogDiscovery:
    return AcpCatalogDiscovery(
        catalog=ProviderCatalog(
            key=key,
            state=CatalogState(
                status=CatalogStatus.UNAVAILABLE,
                checked_at=datetime.now(UTC),
                reason="provider session requires authentication",
            ),
            models=(),
        ),
        authentication=AuthenticationState.UNAUTHENTICATED,
    )


def _text(value: JsonValue | None) -> str | None:
    return (
        value if isinstance(value, str) and value and value == value.strip() else None
    )


def _display(value: JsonValue | None, fallback: str) -> str:
    text = _text(value) or fallback
    return text[:256]


def _description(value: JsonValue | None) -> str | None:
    text = _text(value)
    return None if text is None else text[:1024]


def _local_id(namespace: str, provider_value: str) -> str:
    body = f"{namespace}\0{provider_value}".encode()
    return hashlib.sha256(body).hexdigest()[:32]


def _objects(
    value: JsonValue | None, *, field: str, limit: int
) -> tuple[JsonObject, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise AcpCatalogProtocolError(
            f"ACP catalog field {field!r} must be a list",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    if len(value) > limit:
        raise AcpCatalogProtocolError(
            f"ACP catalog field {field!r} exceeds {limit} items",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    if not all(isinstance(item, dict) for item in value):
        raise AcpCatalogProtocolError(
            f"ACP catalog field {field!r} contains a non-object item",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    return tuple(item for item in value if isinstance(item, dict))


def _flatten_options(
    value: JsonValue | None, *, field: str, limit: int
) -> tuple[JsonObject, ...]:
    flattened: list[JsonObject] = []
    for option in _objects(value, field=field, limit=limit):
        nested = option.get("options")
        if isinstance(nested, list) and _text(option.get("value")) is None:
            flattened.extend(_objects(nested, field=f"{field}.options", limit=limit))
        else:
            flattened.append(option)
    if len(flattened) > limit:
        raise AcpCatalogProtocolError(
            f"ACP catalog field {field!r} exceeds {limit} flattened items",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    return tuple(flattened)


def _option_value(option: JsonObject) -> str | None:
    for field in ("value", "modelId", "id"):
        if value := _text(option.get(field)):
            return value
    return None


def _models_from_options(
    options: tuple[JsonObject, ...], *, namespace: str
) -> tuple[ModelCatalogEntry, ...]:
    models: list[ModelCatalogEntry] = []
    seen: set[str] = set()
    for option in options:
        value = _option_value(option)
        if value is None:
            raise AcpCatalogProtocolError(
                "ACP model option has no provider-issued value",
                code=AcpErrorCode.INTERNAL_ERROR,
            )
        if value in seen:
            raise AcpCatalogProtocolError(
                "ACP model options contain duplicate provider values",
                code=AcpErrorCode.INTERNAL_ERROR,
            )
        seen.add(value)
        models.append(
            ModelCatalogEntry(
                entry_id=_local_id(namespace, value),
                provider_value=value,
                display_name=_display(
                    option.get("name") or option.get("displayName"), value
                ),
                description=_description(option.get("description")),
            )
        )
    return tuple(models)


def _control_from_option(
    option: JsonObject, *, category: str, namespace: str
) -> NativeControl | None:
    if option.get("type") != "select":
        return None
    config_id = _text(option.get("configId")) or _text(option.get("id"))
    if config_id is None:
        raise AcpCatalogProtocolError(
            f"ACP {category} option has no config identifier",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    choices: list[NativeControlOption] = []
    for choice in _flatten_options(
        option.get("options"), field=f"{config_id}.options", limit=_MAX_OPTIONS
    ):
        value = _option_value(choice)
        if value is None:
            raise AcpCatalogProtocolError(
                f"ACP {category} choice has no provider-issued value",
                code=AcpErrorCode.INTERNAL_ERROR,
            )
        choices.append(
            NativeControlOption(
                option_id=_local_id(f"{namespace}:{config_id}", value),
                provider_value=value,
                display_name=_display(
                    choice.get("name") or choice.get("displayName"), value
                ),
                description=_description(choice.get("description")),
            )
        )
    current = option.get("currentValue")
    current_value = current if isinstance(current, str) else None
    default_option_id = (
        _local_id(f"{namespace}:{config_id}", current_value)
        if current_value is not None
        and any(choice.provider_value == current_value for choice in choices)
        else None
    )
    kind = (
        ControlKind.THOUGHT_LEVEL
        if category == "thought_level"
        else ControlKind.MODEL_CONFIG
    )
    return NativeControl(
        control_id=config_id,
        kind=kind,
        display_name=_display(option.get("name"), config_id),
        options=tuple(choices),
        default_option_id=default_option_id,
        description=_description(option.get("description")),
    )


def _normalized_payload(
    result: JsonObject, key: ProviderCatalogKey
) -> tuple[tuple[ModelCatalogEntry, ...], tuple[NativeControl, ...]]:
    models: tuple[ModelCatalogEntry, ...] = ()
    controls: list[NativeControl] = []
    config_options = _objects(
        result.get("configOptions"),
        field="configOptions",
        limit=_MAX_CONTROLS + 1,
    )
    for option in config_options:
        category = _text(option.get("category"))
        if category == "model":
            if models:
                raise AcpCatalogProtocolError(
                    "ACP session advertises multiple model selectors",
                    code=AcpErrorCode.INTERNAL_ERROR,
                )
            models = _models_from_options(
                _flatten_options(
                    option.get("options"), field="model.options", limit=_MAX_MODELS
                ),
                namespace=f"{key.provider_id}:{key.execution_mode}:model",
            )
        elif category in _SUPPORTED_CONTROL_CATEGORIES:
            control = _control_from_option(
                option,
                category=category,
                namespace=f"{key.provider_id}:{key.execution_mode}",
            )
            if control is not None:
                controls.append(control)
                if len(controls) > _MAX_CONTROLS:
                    raise AcpCatalogProtocolError(
                        f"ACP session advertises more than {_MAX_CONTROLS} controls",
                        code=AcpErrorCode.INTERNAL_ERROR,
                    )

    legacy = result.get("models")
    legacy_models = legacy if isinstance(legacy, dict) else {}
    if not models and legacy_models:
        models = _models_from_options(
            _objects(
                legacy_models.get("availableModels"),
                field="models.availableModels",
                limit=_MAX_MODELS,
            ),
            namespace=f"{key.provider_id}:{key.execution_mode}:model",
        )
    return models, tuple(controls)


def _revision(
    key: ProviderCatalogKey,
    models: tuple[ModelCatalogEntry, ...],
    controls: tuple[NativeControl, ...],
) -> str:
    payload = {
        "execution_mode": key.execution_mode,
        "models": [
            {
                "value": model.provider_value,
                "native_control_ids": list(model.native_control_ids),
            }
            for model in models
        ],
        "native_controls": [
            {
                "control_id": control.control_id,
                "options": [option.provider_value for option in control.options],
            }
            for control in controls
        ],
        "provider_id": key.provider_id,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def catalog_from_session_result(
    result: JsonObject,
    *,
    key: ProviderCatalogKey,
    checked_at: datetime | None = None,
) -> ProviderCatalog:
    """Normalize one successful ``session/new`` result into the S01 contract."""
    models, controls = _normalized_payload(result, key)
    if controls:
        control_ids = tuple(control.control_id for control in controls)
        models = tuple(
            replace(model, native_control_ids=control_ids) for model in models
        )
    now = (checked_at or datetime.now(UTC)).astimezone(UTC)
    if not models:
        return ProviderCatalog(
            key=key,
            state=CatalogState(
                status=CatalogStatus.UNAVAILABLE,
                checked_at=now,
                reason="provider session did not advertise model enumeration",
            ),
            models=(),
        )
    return ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=now,
            revision=_revision(key, models, controls),
            expires_at=now + _CATALOG_TTL,
        ),
        models=models,
        native_controls=controls,
    )


async def _read_response(
    stdout: asyncio.StreamReader,
    *,
    request_id: int,
    timeout: float,
    output_budget: OutputBudget,
) -> JsonObject:
    return await read_response(
        stdout,
        request_id=request_id,
        timeout=timeout,
        output_budget=output_budget,
        max_frames=_MAX_FRAMES,
        max_frame_bytes=_MAX_FRAME_BYTES,
        protocol_error=_protocol_error,
    )


async def _request(
    process: asyncio.subprocess.Process,
    *,
    request_id: int,
    method: str,
    params: JsonObject,
    timeout: float,
    output_budget: OutputBudget,
) -> JsonObject:
    if process.stdin is None or process.stdout is None:
        raise AcpCatalogProtocolError("ACP discovery stdio is unavailable")
    request: JsonObject = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }
    process.stdin.write(json.dumps(request).encode() + b"\n")
    await process.stdin.drain()
    response = await _read_response(
        process.stdout,
        request_id=request_id,
        timeout=timeout,
        output_budget=output_budget,
    )
    if "error" in response:
        error = response.get("error")
        raise _rpc_error(method, error)
    result = response.get("result")
    if not isinstance(result, dict):
        raise AcpCatalogProtocolError(f"ACP {method} returned no object result")
    return result


async def discover_acp_catalog(
    command: tuple[str, ...],
    *,
    env: Mapping[str, str],
    cwd: str,
    key: ProviderCatalogKey,
    use_exec: bool = False,
    timeout: float = 30.0,
    metadata: Mapping[str, object] | None = None,
) -> AcpCatalogDiscovery:
    """Discover a provider catalog without sending a completion-bearing prompt."""
    if not command:
        raise ValueError("command must not be empty")
    process = await spawn_acp_process(
        list(command), dict(env), cwd, use_exec=use_exec, metadata=metadata
    )
    output_budget = OutputBudget(_protocol_error)
    stderr_task = asyncio.create_task(
        drain_stderr(process.stderr, process, metadata, output_budget)
    )
    outcome: AcpCatalogDiscovery | None = None
    failure: BaseException | None = None
    try:
        await _request(
            process,
            request_id=0,
            method="initialize",
            params={
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
                "clientInfo": {"name": "vaultspec-catalog", "version": "1.0.0"},
            },
            timeout=timeout,
            output_budget=output_budget,
        )
        session = await _request(
            process,
            request_id=1,
            method="session/new",
            params={"cwd": cwd, "mcpServers": list[JsonValue]()},
            timeout=timeout,
            output_budget=output_budget,
        )
        outcome = AcpCatalogDiscovery(
            catalog=catalog_from_session_result(session, key=key),
            authentication=AuthenticationState.AUTHENTICATED,
        )
    except _AcpCatalogAuthenticationRequiredError:
        outcome = _unauthenticated_discovery(key)
    except BaseException as exc:
        failure = exc

    cleanup_steps: list[CleanupStep] = []
    if process.stdin is not None:
        cleanup_steps.append(("acp-catalog-stdin", process.stdin.close))
    cleanup_steps.extend(
        [
            ("acp-catalog-process", lambda: kill_process_tree(process, metadata)),
            ("acp-catalog-stderr", lambda: cancel_task(stderr_task)),
        ]
    )
    cleanup_failures = await run_independent_cleanups(*cleanup_steps)
    if failure is not None:
        if cleanup_failures:
            failure.add_note(
                "ACP catalog cleanup also failed: "
                + ", ".join(name for name, _ in cleanup_failures)
            )
        raise failure
    if cleanup_failures:
        raise RuntimeError(
            "ACP catalog cleanup failed: "
            + ", ".join(name for name, _ in cleanup_failures)
        )
    if outcome is None:
        raise RuntimeError("ACP catalog discovery completed without an outcome")
    return outcome
