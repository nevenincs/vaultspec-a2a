"""Prompt-free Codex app-server model catalog discovery.

Discovery performs only initialization, account, model-list, and provider-
capability RPCs. It never starts a thread or turn, shares one bounded output
budget across stdout and stderr, and always reaps the contained process tree.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Mapping

from ..utils import package_version
from ._cleanup import CleanupStep, run_independent_cleanups
from ._json_contract import JsonObject, JsonValue
from ._subprocess import kill_process_tree, spawn_acp_process
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
    "CodexCatalogDiscovery",
    "CodexCatalogProtocolError",
    "catalog_from_app_server",
    "discover_codex_catalog",
]

_MAX_FRAME_BYTES: Final = 1_048_576
_MAX_OUTPUT_BYTES: Final = 1_048_576
_MAX_FRAMES_PER_RESPONSE: Final = 64
_MAX_PAGES: Final = 16
_MAX_MODELS: Final = 256
_MAX_CONTROLS: Final = 32
_MAX_OPTIONS: Final = 128
_MODEL_PAGE_SIZE: Final = 100
_CATALOG_TTL: Final = timedelta(minutes=5)
_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)
_CLIENT_INFO: JsonObject = {
    "title": "Vaultspec A2A Catalog",
    "name": "vaultspec-a2a-catalog",
    "version": package_version(),
}


class CodexCatalogProtocolError(RuntimeError):
    """The Codex discovery surface was malformed or exceeded a safety bound."""


@dataclass(frozen=True, slots=True)
class CodexCatalogDiscovery:
    """Prompt-free catalog result plus factual account authentication evidence."""

    catalog: ProviderCatalog
    authentication: AuthenticationState


@dataclass(slots=True)
class _OutputBudget:
    consumed: int = 0

    def charge(self, size: int) -> None:
        self.consumed += size
        if self.consumed > _MAX_OUTPUT_BYTES:
            raise CodexCatalogProtocolError("Codex discovery output exceeds one MiB")


def _text(value: JsonValue | None, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CodexCatalogProtocolError(
            f"Codex catalog field {field!r} must be a normalized non-blank string"
        )
    if len(value) > 1_024:
        raise CodexCatalogProtocolError(
            f"Codex catalog field {field!r} exceeds 1024 characters"
        )
    return value


def _optional_description(value: JsonValue | None) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    return value[:1_024]


def _display(value: JsonValue | None, fallback: str) -> str:
    if isinstance(value, str) and value and value == value.strip():
        return value[:256]
    return fallback[:256]


def _local_id(namespace: str, provider_value: str) -> str:
    encoded = f"{namespace}\0{provider_value}".encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


def _objects(
    value: JsonValue | None, *, field: str, limit: int
) -> tuple[JsonObject, ...]:
    if not isinstance(value, list):
        raise CodexCatalogProtocolError(f"Codex catalog field {field!r} must be a list")
    if len(value) > limit:
        raise CodexCatalogProtocolError(
            f"Codex catalog field {field!r} exceeds {limit} items"
        )
    if not all(isinstance(item, dict) for item in value):
        raise CodexCatalogProtocolError(
            f"Codex catalog field {field!r} contains a non-object item"
        )
    return tuple(item for item in value if isinstance(item, dict))


def _capabilities(result: JsonObject) -> tuple[str, ...]:
    fields = (
        ("webSearch", "web_search"),
        ("imageGeneration", "image_generation"),
        ("namespaceTools", "namespace_tools"),
    )
    capabilities: list[str] = []
    for field, normalized in fields:
        value = result.get(field)
        if not isinstance(value, bool):
            raise CodexCatalogProtocolError(
                f"Codex capability field {field!r} must be a boolean"
            )
        if value:
            capabilities.append(normalized)
    return tuple(capabilities)


def _control(
    *,
    key: ProviderCatalogKey,
    entry_id: str,
    model_name: str,
    field: str,
    kind: ControlKind,
    display_name: str,
    values: tuple[tuple[str, str, str | None], ...],
    default_value: str | None,
) -> NativeControl | None:
    if not values:
        return None
    control_id = f"{field}:{entry_id}"
    namespace = f"{key.provider_id}:{key.execution_mode}:{control_id}"
    seen: set[str] = set()
    options: list[NativeControlOption] = []
    for provider_value, option_name, description in values:
        if provider_value in seen:
            raise CodexCatalogProtocolError(
                f"Codex model {field!r} options contain duplicate values"
            )
        seen.add(provider_value)
        options.append(
            NativeControlOption(
                option_id=_local_id(namespace, provider_value),
                provider_value=provider_value,
                display_name=option_name,
                description=description,
            )
        )
    if len(options) > _MAX_OPTIONS:
        raise CodexCatalogProtocolError(
            f"Codex model {field!r} options exceed {_MAX_OPTIONS} items"
        )
    default_option_id = (
        _local_id(namespace, default_value)
        if default_value is not None and default_value in seen
        else None
    )
    return NativeControl(
        control_id=control_id,
        kind=kind,
        display_name=f"{display_name} for {model_name}"[:256],
        options=tuple(options),
        default_option_id=default_option_id,
    )


def _reasoning_values(model: JsonObject) -> tuple[tuple[str, str, str | None], ...]:
    values: list[tuple[str, str, str | None]] = []
    for index, option in enumerate(
        _objects(
            model.get("supportedReasoningEfforts"),
            field="supportedReasoningEfforts",
            limit=_MAX_OPTIONS,
        )
    ):
        value = _text(
            option.get("reasoningEffort"),
            field=f"supportedReasoningEfforts[{index}].reasoningEffort",
        )
        values.append((value, value, _optional_description(option.get("description"))))
    return tuple(values)


def _service_tier_values(
    model: JsonObject,
) -> tuple[tuple[str, str, str | None], ...]:
    service_tiers = model.get("serviceTiers")
    if isinstance(service_tiers, list) and service_tiers:
        values: list[tuple[str, str, str | None]] = []
        for index, option in enumerate(
            _objects(service_tiers, field="serviceTiers", limit=_MAX_OPTIONS)
        ):
            value = _text(option.get("id"), field=f"serviceTiers[{index}].id")
            values.append(
                (
                    value,
                    _display(option.get("name"), value),
                    _optional_description(option.get("description")),
                )
            )
        return tuple(values)
    speed_tiers = model.get("additionalSpeedTiers")
    if speed_tiers is None:
        return ()
    if not isinstance(speed_tiers, list) or len(speed_tiers) > _MAX_OPTIONS:
        raise CodexCatalogProtocolError(
            "Codex catalog field 'additionalSpeedTiers' must be a bounded list"
        )
    return tuple(
        (
            _text(value, field=f"additionalSpeedTiers[{index}]"),
            _text(value, field=f"additionalSpeedTiers[{index}]"),
            None,
        )
        for index, value in enumerate(speed_tiers)
    )


def _revision(
    key: ProviderCatalogKey,
    models: tuple[ModelCatalogEntry, ...],
    controls: tuple[NativeControl, ...],
) -> str:
    payload = {
        "provider_id": key.provider_id,
        "execution_mode": key.execution_mode,
        "models": [
            {
                "value": model.provider_value,
                "capabilities": list(model.capabilities),
                "native_control_ids": list(model.native_control_ids),
            }
            for model in models
        ],
        "controls": [
            {
                "id": control.control_id,
                "default": control.default_option_id,
                "values": [option.provider_value for option in control.options],
            }
            for control in controls
        ],
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def catalog_from_app_server(
    model_pages: tuple[JsonObject, ...],
    capabilities_result: JsonObject,
    *,
    key: ProviderCatalogKey,
    checked_at: datetime | None = None,
) -> ProviderCatalog:
    """Normalize ordered app-server pages and capabilities into the S01 contract."""
    capabilities = _capabilities(capabilities_result)
    models: list[ModelCatalogEntry] = []
    controls: list[NativeControl] = []
    seen_models: set[str] = set()
    for page_index, page in enumerate(model_pages):
        remaining = _MAX_MODELS - len(models)
        page_models = _objects(
            page.get("data"), field=f"pages[{page_index}].data", limit=_MAX_MODELS
        )
        if len(page_models) > remaining:
            raise CodexCatalogProtocolError(
                f"Codex catalog exceeds {_MAX_MODELS} models"
            )
        for model_index, model in enumerate(page_models):
            value = _text(
                model.get("model"),
                field=f"pages[{page_index}].data[{model_index}].model",
            )
            if value in seen_models:
                raise CodexCatalogProtocolError(
                    "Codex catalog contains duplicate model values"
                )
            seen_models.add(value)
            entry_id = _local_id(f"{key.provider_id}:{key.execution_mode}:model", value)
            model_name = _display(model.get("displayName"), value)
            raw_default_effort = model.get("defaultReasoningEffort")
            default_effort = (
                raw_default_effort if isinstance(raw_default_effort, str) else None
            )
            reasoning = _control(
                key=key,
                entry_id=entry_id,
                model_name=model_name,
                field="reasoning_effort",
                kind=ControlKind.THOUGHT_LEVEL,
                display_name="Reasoning effort",
                values=_reasoning_values(model),
                default_value=default_effort,
            )
            raw_default_tier = model.get("defaultServiceTier")
            default_tier = (
                raw_default_tier if isinstance(raw_default_tier, str) else None
            )
            service_tier = _control(
                key=key,
                entry_id=entry_id,
                model_name=model_name,
                field="service_tier",
                kind=ControlKind.SERVICE_TIER,
                display_name="Service tier",
                values=_service_tier_values(model),
                default_value=default_tier,
            )
            controls.extend(
                control for control in (reasoning, service_tier) if control is not None
            )
            models.append(
                ModelCatalogEntry(
                    entry_id=entry_id,
                    provider_value=value,
                    display_name=model_name,
                    description=_optional_description(model.get("description")),
                    capabilities=capabilities,
                    native_control_ids=tuple(
                        control.control_id
                        for control in (reasoning, service_tier)
                        if control is not None
                    ),
                )
            )
            if len(controls) > _MAX_CONTROLS:
                raise CodexCatalogProtocolError(
                    f"Codex catalog exceeds {_MAX_CONTROLS} native controls"
                )
    now = (checked_at or datetime.now(UTC)).astimezone(UTC)
    if not models:
        return ProviderCatalog(
            key=key,
            state=CatalogState(
                status=CatalogStatus.UNAVAILABLE,
                checked_at=now,
                reason="Codex app-server advertised no models",
            ),
            models=(),
        )
    normalized_controls = tuple(controls)
    normalized_models = tuple(models)
    return ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=now,
            revision=_revision(key, normalized_models, normalized_controls),
            expires_at=now + _CATALOG_TTL,
        ),
        models=normalized_models,
        native_controls=normalized_controls,
    )


def _authentication(result: JsonObject) -> AuthenticationState:
    requires_auth = result.get("requiresOpenaiAuth")
    if not isinstance(requires_auth, bool):
        raise CodexCatalogProtocolError(
            "Codex account/read requiresOpenaiAuth must be a boolean"
        )
    account = result.get("account")
    if isinstance(account, dict):
        return AuthenticationState.AUTHENTICATED
    if account is not None:
        raise CodexCatalogProtocolError(
            "Codex account/read account must be an object or null"
        )
    return (
        AuthenticationState.UNAUTHENTICATED
        if requires_auth
        else AuthenticationState.NOT_APPLICABLE
    )


def _rpc_error(method: str, _error: JsonValue) -> CodexCatalogProtocolError:
    return CodexCatalogProtocolError(f"Codex {method} failed with a provider error")


async def _read_response(
    stdout: asyncio.StreamReader,
    *,
    request_id: int,
    timeout: float,
    output_budget: _OutputBudget,
) -> JsonObject:
    for _ in range(_MAX_FRAMES_PER_RESPONSE):
        raw = await asyncio.wait_for(stdout.readline(), timeout=timeout)
        if not raw:
            break
        if len(raw) > _MAX_FRAME_BYTES:
            raise CodexCatalogProtocolError("Codex discovery frame exceeds one MiB")
        output_budget.charge(len(raw))
        try:
            value = _JSON_OBJECT.validate_json(raw)
        except (ValidationError, UnicodeDecodeError):
            continue
        if value.get("id") == request_id:
            return value
    raise CodexCatalogProtocolError(
        f"Codex discovery received no response for request {request_id}"
    )


async def _request(
    process: asyncio.subprocess.Process,
    *,
    request_id: int,
    method: str,
    params: JsonObject,
    timeout: float,
    output_budget: _OutputBudget,
) -> JsonObject:
    if process.stdin is None or process.stdout is None:
        raise CodexCatalogProtocolError("Codex discovery stdio is unavailable")
    request: JsonObject = {"id": request_id, "method": method, "params": params}
    process.stdin.write(json.dumps(request).encode() + b"\n")
    await process.stdin.drain()
    response = await _read_response(
        process.stdout,
        request_id=request_id,
        timeout=timeout,
        output_budget=output_budget,
    )
    if "error" in response:
        raise _rpc_error(method, response["error"])
    result = response.get("result")
    if not isinstance(result, dict):
        raise CodexCatalogProtocolError(f"Codex {method} returned no object result")
    return result


async def _notify_initialized(process: asyncio.subprocess.Process) -> None:
    if process.stdin is None:
        raise CodexCatalogProtocolError("Codex discovery stdin is unavailable")
    process.stdin.write(
        json.dumps({"method": "initialized", "params": {}}).encode() + b"\n"
    )
    await process.stdin.drain()


async def _drain_stderr(
    stderr: asyncio.StreamReader | None,
    process: asyncio.subprocess.Process,
    metadata: Mapping[str, object] | None,
    output_budget: _OutputBudget,
) -> None:
    if stderr is None:
        return
    while chunk := await stderr.read(65_536):
        try:
            output_budget.charge(len(chunk))
        except CodexCatalogProtocolError:
            await kill_process_tree(process, metadata)
            raise


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def discover_codex_catalog(
    command: tuple[str, ...],
    *,
    env: Mapping[str, str],
    cwd: str,
    key: ProviderCatalogKey,
    timeout: float = 30.0,
    metadata: Mapping[str, object] | None = None,
) -> CodexCatalogDiscovery:
    """Discover Codex models and controls without starting a completion."""
    if not command:
        raise ValueError("command must not be empty")
    process = await spawn_acp_process(
        list(command), dict(env), cwd, use_exec=False, metadata=metadata
    )
    output_budget = _OutputBudget()
    stderr_task = asyncio.create_task(
        _drain_stderr(process.stderr, process, metadata, output_budget)
    )
    outcome: CodexCatalogDiscovery | None = None
    failure: BaseException | None = None
    try:
        request_id = 1
        await _request(
            process,
            request_id=request_id,
            method="initialize",
            params={"clientInfo": _CLIENT_INFO, "capabilities": {}},
            timeout=timeout,
            output_budget=output_budget,
        )
        await _notify_initialized(process)
        request_id += 1
        account = await _request(
            process,
            request_id=request_id,
            method="account/read",
            params={"refreshToken": False},
            timeout=timeout,
            output_budget=output_budget,
        )
        request_id += 1
        pages: list[JsonObject] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(_MAX_PAGES):
            page = await _request(
                process,
                request_id=request_id,
                method="model/list",
                params={
                    "cursor": cursor,
                    "limit": _MODEL_PAGE_SIZE,
                    "includeHidden": False,
                },
                timeout=timeout,
                output_budget=output_budget,
            )
            request_id += 1
            pages.append(page)
            next_cursor = page.get("nextCursor")
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor:
                raise CodexCatalogProtocolError(
                    "Codex model/list nextCursor must be a non-blank string or null"
                )
            if next_cursor in seen_cursors:
                raise CodexCatalogProtocolError(
                    "Codex model/list pagination repeated a cursor"
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise CodexCatalogProtocolError(
                f"Codex model/list exceeds {_MAX_PAGES} pages"
            )
        capabilities = await _request(
            process,
            request_id=request_id,
            method="modelProvider/capabilities/read",
            params={},
            timeout=timeout,
            output_budget=output_budget,
        )
        outcome = CodexCatalogDiscovery(
            catalog=catalog_from_app_server(tuple(pages), capabilities, key=key),
            authentication=_authentication(account),
        )
    except BaseException as exc:
        failure = exc

    cleanup_steps: list[CleanupStep] = []
    if process.stdin is not None:
        cleanup_steps.append(("codex-catalog-stdin", process.stdin.close))
    cleanup_steps.extend(
        [
            ("codex-catalog-process", lambda: kill_process_tree(process, metadata)),
            ("codex-catalog-stderr", lambda: _cancel(stderr_task)),
        ]
    )
    cleanup_failures = await run_independent_cleanups(*cleanup_steps)
    if failure is not None:
        output_failure = next(
            (
                exc
                for name, exc in cleanup_failures
                if name == "codex-catalog-stderr"
                and isinstance(exc, CodexCatalogProtocolError)
            ),
            None,
        )
        if output_failure is not None:
            output_failure.add_note(
                f"Codex discovery also failed with {type(failure).__name__}"
            )
            raise output_failure
        if cleanup_failures:
            failure.add_note(
                "Codex catalog cleanup also failed: "
                + ", ".join(name for name, _ in cleanup_failures)
            )
        raise failure
    if cleanup_failures:
        raise RuntimeError(
            "Codex catalog cleanup failed: "
            + ", ".join(name for name, _ in cleanup_failures)
        )
    if outcome is None:
        raise RuntimeError("Codex catalog discovery completed without an outcome")
    return outcome
