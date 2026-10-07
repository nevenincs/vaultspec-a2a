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
from dataclasses import replace
from typing import TYPE_CHECKING, Final, TypedDict, Unpack, cast

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from ..desktop.native_isolation import NativeLaunchAuthority
    from ._cleanup import CleanupStep
from ._acp_auth import is_auth_required_error
from ._catalog_discovery import (
    ProviderCatalogDiscovery,
    available_catalog,
    finish_discovery,
    unavailable_catalog,
    unavailable_discovery,
)
from ._catalog_fields import (
    MAX_DISCOVERY_FRAMES,
    MAX_DISCOVERY_READ_BYTES,
    CatalogFieldReader,
    display_text,
    local_id,
    optional_description,
    optional_text,
)
from ._json_contract import JsonObject, JsonValue, lenient_json_object
from ._stdio_rpc import OutputBudget, cancel_task, drain_stderr, read_response
from ._subprocess import kill_process_tree, spawn_acp_process
from .acp_exceptions import AcpErrorCode, AcpSessionError
from .provider_catalog import (
    MAX_CONTROLS,
    MAX_MODELS,
    MAX_OPTIONS,
    AuthenticationState,
    ControlKind,
    ModelCatalogEntry,
    NativeControl,
    NativeControlOption,
    ProviderCatalog,
    ProviderCatalogKey,
)

__all__ = [
    "AcpCatalogProtocolError",
    "catalog_from_session_result",
    "discover_acp_catalog",
]

_SUPPORTED_CONTROL_CATEGORIES: Final = frozenset({"thought_level", "model_config"})


class AcpCatalogProtocolError(AcpSessionError):
    """The ACP discovery surface was malformed or exceeded a safety bound."""


class _AcpCatalogAuthenticationRequiredError(AcpSessionError):
    """Internal signal used to return factual unauthenticated evidence."""


def _protocol_error(message: str) -> AcpCatalogProtocolError:
    """Raise ACP's own dialect of a discovery protocol refusal."""
    return AcpCatalogProtocolError(f"ACP {message}", code=AcpErrorCode.INTERNAL_ERROR)


_FIELDS: Final = CatalogFieldReader(_protocol_error)


def _rpc_error(method: str, error: JsonValue) -> AcpSessionError:
    """Classify an ACP failure without retaining provider-controlled text."""
    detail = lenient_json_object(error)
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


def _unauthenticated_discovery(key: ProviderCatalogKey) -> ProviderCatalogDiscovery:
    return unavailable_discovery(
        key,
        reason="provider session requires authentication",
        authentication=AuthenticationState.UNAUTHENTICATED,
    )


def _flatten_options(
    value: JsonValue | None, *, field: str, limit: int
) -> tuple[JsonObject, ...]:
    flattened: list[JsonObject] = []
    for option in _FIELDS.optional_objects(value, field=field, limit=limit):
        nested = option.get("options")
        if isinstance(nested, list) and optional_text(option.get("value")) is None:
            flattened.extend(
                _FIELDS.optional_objects(nested, field=f"{field}.options", limit=limit)
            )
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
        if value := optional_text(option.get(field)):
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
                entry_id=local_id(namespace, value),
                provider_value=value,
                display_name=display_text(
                    option.get("name") or option.get("displayName"), value
                ),
                description=optional_description(option.get("description")),
            )
        )
    return tuple(models)


def _control_options(
    option: JsonObject,
    *,
    category: str,
    namespace: str,
    config_id: str,
) -> tuple[NativeControlOption, ...]:
    choices: list[NativeControlOption] = []
    for choice in _flatten_options(
        option.get("options"), field=f"{config_id}.options", limit=MAX_OPTIONS
    ):
        value = _option_value(choice)
        if value is None:
            raise AcpCatalogProtocolError(
                f"ACP {category} choice has no provider-issued value",
                code=AcpErrorCode.INTERNAL_ERROR,
            )
        choices.append(
            NativeControlOption(
                option_id=local_id(f"{namespace}:{config_id}", value),
                provider_value=value,
                display_name=display_text(
                    choice.get("name") or choice.get("displayName"), value
                ),
                description=optional_description(choice.get("description")),
            )
        )
    return tuple(choices)


def _control_from_option(
    option: JsonObject, *, category: str, namespace: str
) -> NativeControl | None:
    if option.get("type") != "select":
        return None
    config_id = optional_text(option.get("configId")) or optional_text(option.get("id"))
    if config_id is None:
        raise AcpCatalogProtocolError(
            f"ACP {category} option has no config identifier",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    choices = _control_options(
        option,
        category=category,
        namespace=namespace,
        config_id=config_id,
    )
    current = option.get("currentValue")
    current_value = current if isinstance(current, str) else None
    default_option_id = (
        local_id(f"{namespace}:{config_id}", current_value)
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
        display_name=display_text(option.get("name"), config_id),
        options=tuple(choices),
        default_option_id=default_option_id,
        description=optional_description(option.get("description")),
    )


def _normalized_payload(
    result: JsonObject, key: ProviderCatalogKey
) -> tuple[tuple[ModelCatalogEntry, ...], tuple[NativeControl, ...]]:
    models: tuple[ModelCatalogEntry, ...] = ()
    controls: list[NativeControl] = []
    config_options = _FIELDS.optional_objects(
        result.get("configOptions"),
        field="configOptions",
        # ACP carries the model selector in the same list as the controls, so a
        # session advertising the full complement of controls plus its one model
        # selector is legitimate and must survive this early bound.
        limit=MAX_CONTROLS + 1,
    )
    for option in config_options:
        category = optional_text(option.get("category"))
        if category == "model":
            if models:
                raise AcpCatalogProtocolError(
                    "ACP session advertises multiple model selectors",
                    code=AcpErrorCode.INTERNAL_ERROR,
                )
            models = _models_from_options(
                _flatten_options(
                    option.get("options"), field="model.options", limit=MAX_MODELS
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
                if len(controls) > MAX_CONTROLS:
                    raise AcpCatalogProtocolError(
                        f"ACP session advertises more than {MAX_CONTROLS} controls",
                        code=AcpErrorCode.INTERNAL_ERROR,
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
    """Normalize one successful ``session/new`` result into the catalog contract."""
    models, controls = _normalized_payload(result, key)
    if controls:
        control_ids = tuple(control.control_id for control in controls)
        models = tuple(
            replace(model, native_control_ids=control_ids) for model in models
        )
    if not models:
        return unavailable_catalog(
            key,
            reason="provider session did not advertise model enumeration",
            checked_at=checked_at,
        )
    return available_catalog(
        key,
        revision=_revision(key, models, controls),
        models=models,
        native_controls=controls,
        checked_at=checked_at,
    )


class _RequestOptions(TypedDict):
    request_id: int
    method: str
    params: JsonObject
    timeout: float
    output_budget: OutputBudget


async def _request(
    process: asyncio.subprocess.Process,
    **options: Unpack[_RequestOptions],
) -> JsonObject:
    request_id = options["request_id"]
    method = options["method"]
    params = options["params"]
    timeout = options["timeout"]
    output_budget = options["output_budget"]
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
    response = await read_response(
        process.stdout,
        request_id=request_id,
        timeout=timeout,
        output_budget=output_budget,
        max_frames=MAX_DISCOVERY_FRAMES,
        max_frame_bytes=MAX_DISCOVERY_READ_BYTES,
        protocol_error=_protocol_error,
    )
    if "error" in response:
        error = response.get("error")
        raise _rpc_error(method, error)
    result = response.get("result")
    if not isinstance(result, dict):
        raise AcpCatalogProtocolError(f"ACP {method} returned no object result")
    return result


class _DiscoverAcpCatalogRequired(TypedDict):
    env: Mapping[str, str]
    cwd: str
    key: ProviderCatalogKey


class _DiscoverAcpCatalogOptions(_DiscoverAcpCatalogRequired, total=False):
    native_authority: NativeLaunchAuthority | None
    use_exec: bool
    timeout: float
    metadata: Mapping[str, object] | None
    # The lane-specific ``session/new`` ``_meta`` block, supplied by the caller
    # that knows which lane this is. Discovery itself stays lane-agnostic: it
    # speaks ACP, and the namespaces inside ``_meta`` belong to one backend
    # each. It is forwarded rather than composed here because the posture a
    # probe opens its session under has to be the posture the served turn will
    # run under - a probe that qualified a lane under different session options
    # qualified a lane nobody will run.
    session_meta: Mapping[str, object] | None


async def discover_acp_catalog(
    command: tuple[str, ...],
    **options: Unpack[_DiscoverAcpCatalogOptions],
) -> ProviderCatalogDiscovery:
    """Discover a provider catalog without sending a completion-bearing prompt."""
    env = options["env"]
    cwd = options["cwd"]
    key = options["key"]
    use_exec = options.get("use_exec", False)
    timeout = options.get("timeout", 30.0)
    metadata = options.get("metadata")
    session_meta = options.get("session_meta")
    if not command:
        raise ValueError("command must not be empty")
    process = await spawn_acp_process(
        list(command),
        dict(env),
        cwd,
        use_exec=use_exec,
        metadata=metadata,
        native_authority=options.get("native_authority"),
    )
    output_budget = OutputBudget(_protocol_error)
    stderr_task = asyncio.create_task(
        drain_stderr(process.stderr, process, metadata, output_budget)
    )
    outcome: ProviderCatalogDiscovery | None = None
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
        # Prompt-free, but still a REAL session: the CLI partitions its config
        # home by this cwd and writes a transcript there, exactly as a run's
        # session does. That makes discovery a creating seam for
        # acp-cli-session-transcript (declared in ``acp_chat_model``) and the
        # higher-frequency one, since one catalog read probes every lane. A
        # caller passing a per-invocation directory leaves a partition per
        # invocation behind; passing a stable one leaves a single partition.
        session_params: JsonObject = {"cwd": cwd, "mcpServers": list[JsonValue]()}
        if session_meta is not None:
            session_params["_meta"] = cast("JsonValue", dict(session_meta))
        session = await _request(
            process,
            request_id=1,
            method="session/new",
            params=session_params,
            timeout=timeout,
            output_budget=output_budget,
        )
        outcome = ProviderCatalogDiscovery(
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
    return await finish_discovery(
        "ACP", outcome, failure, cleanup_steps, AcpCatalogProtocolError
    )
