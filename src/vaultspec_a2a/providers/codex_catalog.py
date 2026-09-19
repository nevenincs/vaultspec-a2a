"""Prompt-free Codex app-server model catalog discovery.

Discovery performs only initialization, account, model-list, and provider-
capability RPCs. It never starts a thread or turn, shares one bounded output
budget across stdout and stderr, and always reaps the contained process tree.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ._json_contract import JsonObject, JsonValue

from ..utils import package_version
from ._catalog_fields import (
    CatalogFieldReader,
    display_label,
    display_text,
    local_id,
    optional_description,
)
from ._cleanup import CleanupStep, run_independent_cleanups
from ._stdio_rpc import OutputBudget, cancel_task, drain_stderr, read_response
from ._subprocess import kill_process_tree, spawn_acp_process
from .provider_catalog import (
    MAX_CONTROLS,
    MAX_MODELS,
    MAX_OPTIONS,
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
    "CodexCatalogProtocolError",
    "catalog_from_app_server",
    "discover_codex_catalog",
]

_MAX_FRAME_BYTES: Final = 1_048_576
_MAX_FRAMES_PER_RESPONSE: Final = 64
_MAX_PAGES: Final = 16
_MODEL_PAGE_SIZE: Final = 100
_CATALOG_TTL: Final = timedelta(minutes=5)
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


def _protocol_error(message: str) -> CodexCatalogProtocolError:
    """Raise Codex's own dialect of a discovery protocol refusal."""
    return CodexCatalogProtocolError(f"Codex {message}")


_FIELDS: Final = CatalogFieldReader(_protocol_error)


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
    for field_name, normalized in fields:
        value = result.get(field_name)
        if not isinstance(value, bool):
            raise CodexCatalogProtocolError(
                f"Codex capability field {field_name!r} must be a boolean"
            )
        if value:
            capabilities.append(normalized)
    return tuple(capabilities)


@dataclass(frozen=True, slots=True)
class _ControlSpec:
    field: str
    kind: ControlKind
    display_name: str
    values: tuple[tuple[str, str, str | None], ...]
    default_value: str | None


def _control(
    key: ProviderCatalogKey,
    entry_id: str,
    model_name: str,
    spec: _ControlSpec,
) -> NativeControl | None:
    if not spec.values:
        return None
    control_id = f"{spec.field}:{entry_id}"
    namespace = f"{key.provider_id}:{key.execution_mode}:{control_id}"
    seen: set[str] = set()
    options: list[NativeControlOption] = []
    for provider_value, option_name, description in spec.values:
        if provider_value in seen:
            raise CodexCatalogProtocolError(
                f"Codex model {spec.field!r} options contain duplicate values"
            )
        seen.add(provider_value)
        options.append(
            NativeControlOption(
                option_id=local_id(namespace, provider_value),
                provider_value=provider_value,
                display_name=option_name,
                description=description,
            )
        )
    if len(options) > MAX_OPTIONS:
        raise CodexCatalogProtocolError(
            f"Codex model {spec.field!r} options exceed {MAX_OPTIONS} items"
        )
    default_option_id = (
        local_id(namespace, spec.default_value)
        if spec.default_value is not None and spec.default_value in seen
        else None
    )
    return NativeControl(
        control_id=control_id,
        kind=spec.kind,
        display_name=display_label(f"{spec.display_name} for {model_name}"),
        options=tuple(options),
        default_option_id=default_option_id,
    )


def _reasoning_values(model: JsonObject) -> tuple[tuple[str, str, str | None], ...]:
    values: list[tuple[str, str, str | None]] = []
    for index, option in enumerate(
        _objects(
            model.get("supportedReasoningEfforts"),
            field="supportedReasoningEfforts",
            limit=MAX_OPTIONS,
        )
    ):
        value = _FIELDS.required_text(
            option.get("reasoningEffort"),
            field=f"supportedReasoningEfforts[{index}].reasoningEffort",
        )
        values.append((value, value, optional_description(option.get("description"))))
    return tuple(values)


def _service_tier_values(
    model: JsonObject,
) -> tuple[tuple[str, str, str | None], ...]:
    service_tiers = model.get("serviceTiers")
    if service_tiers is None:
        return ()
    values: list[tuple[str, str, str | None]] = []
    for index, option in enumerate(
        _objects(service_tiers, field="serviceTiers", limit=MAX_OPTIONS)
    ):
        value = _FIELDS.required_text(
            option.get("id"), field=f"serviceTiers[{index}].id"
        )
        values.append(
            (
                value,
                display_text(option.get("name"), value),
                optional_description(option.get("description")),
            )
        )
    return tuple(values)


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


@dataclass(slots=True)
class _CatalogBuilder:
    key: ProviderCatalogKey
    capabilities: tuple[str, ...]
    models: list[ModelCatalogEntry] = field(default_factory=list)
    controls: list[NativeControl] = field(default_factory=list)
    seen_models: set[str] = field(default_factory=set)

    def add_page(self, page: JsonObject, page_index: int) -> None:
        """Validate one bounded page before adding its models in source order."""
        remaining = MAX_MODELS - len(self.models)
        page_models = _objects(
            page.get("data"), field=f"pages[{page_index}].data", limit=MAX_MODELS
        )
        if len(page_models) > remaining:
            raise CodexCatalogProtocolError(
                f"Codex catalog exceeds {MAX_MODELS} models"
            )
        for model_index, model in enumerate(page_models):
            self.add_model(model, page_index, model_index)

    def add_model(self, model: JsonObject, page_index: int, model_index: int) -> None:
        """Normalize one provider model and its bounded native controls."""
        value = _FIELDS.required_text(
            model.get("model"),
            field=f"pages[{page_index}].data[{model_index}].model",
        )
        if value in self.seen_models:
            raise CodexCatalogProtocolError(
                "Codex catalog contains duplicate model values"
            )
        self.seen_models.add(value)
        entry_id = local_id(
            f"{self.key.provider_id}:{self.key.execution_mode}:model", value
        )
        model_name = display_text(model.get("displayName"), value)
        raw_default_effort = model.get("defaultReasoningEffort")
        default_effort = (
            raw_default_effort if isinstance(raw_default_effort, str) else None
        )
        reasoning = _control(
            self.key,
            entry_id,
            model_name,
            _ControlSpec(
                field="reasoning_effort",
                kind=ControlKind.THOUGHT_LEVEL,
                display_name="Reasoning effort",
                values=_reasoning_values(model),
                default_value=default_effort,
            ),
        )
        raw_default_tier = model.get("defaultServiceTier")
        default_tier = raw_default_tier if isinstance(raw_default_tier, str) else None
        service_tier = _control(
            self.key,
            entry_id,
            model_name,
            _ControlSpec(
                field="service_tier",
                kind=ControlKind.SERVICE_TIER,
                display_name="Service tier",
                values=_service_tier_values(model),
                default_value=default_tier,
            ),
        )
        self.controls.extend(
            control for control in (reasoning, service_tier) if control is not None
        )
        self.models.append(
            ModelCatalogEntry(
                entry_id=entry_id,
                provider_value=value,
                display_name=model_name,
                description=optional_description(model.get("description")),
                capabilities=self.capabilities,
                native_control_ids=tuple(
                    control.control_id
                    for control in (reasoning, service_tier)
                    if control is not None
                ),
            )
        )
        if len(self.controls) > MAX_CONTROLS:
            raise CodexCatalogProtocolError(
                f"Codex catalog exceeds {MAX_CONTROLS} native controls"
            )


def catalog_from_app_server(
    model_pages: tuple[JsonObject, ...],
    capabilities_result: JsonObject,
    *,
    key: ProviderCatalogKey,
    checked_at: datetime | None = None,
) -> ProviderCatalog:
    """Normalize ordered app-server pages and capabilities into the catalog contract."""
    builder = _CatalogBuilder(key, _capabilities(capabilities_result))
    for page_index, page in enumerate(model_pages):
        builder.add_page(page, page_index)
    now = (checked_at or datetime.now(UTC)).astimezone(UTC)
    if not builder.models:
        return ProviderCatalog(
            key=key,
            state=CatalogState(
                status=CatalogStatus.UNAVAILABLE,
                checked_at=now,
                reason="Codex app-server advertised no models",
            ),
            models=(),
        )
    normalized_controls = tuple(builder.controls)
    normalized_models = tuple(builder.models)
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
    output_budget: OutputBudget,
) -> JsonObject:
    return await read_response(
        stdout,
        request_id=request_id,
        timeout=timeout,
        output_budget=output_budget,
        max_frames=_MAX_FRAMES_PER_RESPONSE,
        max_frame_bytes=_MAX_FRAME_BYTES,
        protocol_error=_protocol_error,
    )


@dataclass(frozen=True, slots=True)
class _CatalogRpc:
    process: asyncio.subprocess.Process
    timeout: float
    output_budget: OutputBudget

    async def request(
        self, request_id: int, method: str, params: JsonObject
    ) -> JsonObject:
        """Send one bounded JSON-RPC call over this discovery process."""
        if self.process.stdin is None or self.process.stdout is None:
            raise CodexCatalogProtocolError("Codex discovery stdio is unavailable")
        request: JsonObject = {"id": request_id, "method": method, "params": params}
        self.process.stdin.write(json.dumps(request).encode() + b"\n")
        await self.process.stdin.drain()
        response = await _read_response(
            self.process.stdout,
            request_id=request_id,
            timeout=self.timeout,
            output_budget=self.output_budget,
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


async def _read_model_pages(
    rpc: _CatalogRpc,
    request_id: int,
) -> tuple[tuple[JsonObject, ...], int]:
    """Read bounded model pages and return the next free JSON-RPC request id."""
    pages: list[JsonObject] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(_MAX_PAGES):
        page = await rpc.request(
            request_id,
            "model/list",
            {
                "cursor": cursor,
                "limit": _MODEL_PAGE_SIZE,
                "includeHidden": False,
            },
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
        raise CodexCatalogProtocolError(f"Codex model/list exceeds {_MAX_PAGES} pages")
    return tuple(pages), request_id


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
    output_budget = OutputBudget(_protocol_error)
    rpc = _CatalogRpc(process, timeout, output_budget)
    stderr_task = asyncio.create_task(
        drain_stderr(process.stderr, process, metadata, output_budget)
    )
    outcome: CodexCatalogDiscovery | None = None
    failure: BaseException | None = None
    try:
        request_id = 1
        await rpc.request(
            request_id,
            "initialize",
            {"clientInfo": _CLIENT_INFO, "capabilities": {}},
        )
        await _notify_initialized(process)
        request_id += 1
        account = await rpc.request(
            request_id,
            "account/read",
            {"refreshToken": False},
        )
        request_id += 1
        pages, request_id = await _read_model_pages(rpc, request_id)
        capabilities = await rpc.request(
            request_id,
            "modelProvider/capabilities/read",
            {},
        )
        outcome = CodexCatalogDiscovery(
            catalog=catalog_from_app_server(pages, capabilities, key=key),
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
            ("codex-catalog-stderr", lambda: cancel_task(stderr_task)),
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
