"""Prompt-free Kimi CLI configured-lane catalog discovery.

The installed CLI's ``provider list --json`` command is the sole discovery
surface. Its provider table may contain credentials, so normalization retains
only model aliases, safe display metadata, capabilities, and advertised
thinking efforts. Raw provider records and diagnostic output never escape.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Mapping

from ._catalog_fields import (
    CatalogFieldReader,
    display_label,
    display_text,
    local_id,
)
from ._cleanup import CleanupStep, run_independent_cleanups
from ._json_contract import JsonObject, JsonValue
from ._stdio_rpc import OutputBudget, cancel_task
from ._subprocess import kill_process_tree, spawn_acp_process
from .provider_catalog import (
    MAX_CAPABILITIES,
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
    "KimiCatalogDiscovery",
    "KimiCatalogProtocolError",
    "catalog_from_provider_list",
    "discover_kimi_catalog",
]

_CATALOG_TTL: Final = timedelta(minutes=5)
_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class KimiCatalogProtocolError(RuntimeError):
    """Kimi discovery returned malformed data or exceeded a safety bound."""


@dataclass(frozen=True, slots=True)
class KimiCatalogDiscovery:
    """Configured Kimi catalog plus deliberately unknown authentication evidence."""

    catalog: ProviderCatalog
    authentication: AuthenticationState = AuthenticationState.UNKNOWN


def _protocol_error(message: str) -> KimiCatalogProtocolError:
    """Raise Kimi's own dialect of a discovery protocol refusal."""
    return KimiCatalogProtocolError(f"Kimi {message}")


_FIELDS: Final = CatalogFieldReader(_protocol_error)


def _object_table(value: JsonValue | None, *, field: str) -> JsonObject:
    if not isinstance(value, dict):
        raise KimiCatalogProtocolError(
            f"Kimi catalog field {field!r} must be an object"
        )
    return value


def _string_list(
    value: JsonValue | None,
    *,
    field: str,
    limit: int,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise KimiCatalogProtocolError(f"Kimi catalog field {field!r} must be a list")
    if len(value) > limit:
        raise KimiCatalogProtocolError(
            f"Kimi catalog field {field!r} exceeds {limit} items"
        )
    values = tuple(
        _FIELDS.required_text(item, field=f"{field}[{index}]")
        for index, item in enumerate(value)
    )
    if len(values) != len(set(values)):
        raise KimiCatalogProtocolError(
            f"Kimi catalog field {field!r} contains duplicate values"
        )
    return values


def _thinking_control(
    model: JsonObject,
    *,
    key: ProviderCatalogKey,
    entry_id: str,
    display_name: str,
) -> NativeControl | None:
    efforts = _string_list(
        model.get("supportEfforts"),
        field="supportEfforts",
        limit=MAX_OPTIONS,
    )
    if not efforts:
        return None
    control_id = f"thinking_effort:{entry_id}"
    namespace = f"{key.provider_id}:{key.execution_mode}:{control_id}"
    options = tuple(
        NativeControlOption(
            option_id=local_id(namespace, effort),
            provider_value=effort,
            display_name=effort,
        )
        for effort in efforts
    )
    raw_default = model.get("defaultEffort")
    default_effort = raw_default if isinstance(raw_default, str) else None
    default_option_id = (
        local_id(namespace, default_effort)
        if default_effort is not None and default_effort in efforts
        else None
    )
    return NativeControl(
        control_id=control_id,
        kind=ControlKind.THOUGHT_LEVEL,
        display_name=display_label(f"Thinking effort for {display_name}"),
        options=options,
        default_option_id=default_option_id,
    )


def _revision(
    key: ProviderCatalogKey,
    rows: tuple[JsonObject, ...],
    controls: tuple[NativeControl, ...],
) -> str:
    payload = {
        "provider_id": key.provider_id,
        "execution_mode": key.execution_mode,
        "models": rows,
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


def catalog_from_provider_list(
    result: JsonObject,
    *,
    key: ProviderCatalogKey,
    checked_at: datetime | None = None,
) -> ProviderCatalog:
    """Normalize ``kimi provider list --json`` without retaining provider secrets."""
    providers = _object_table(result.get("providers"), field="providers")
    model_table = _object_table(result.get("models"), field="models")
    if len(model_table) > MAX_MODELS:
        raise KimiCatalogProtocolError(
            f"Kimi catalog field 'models' exceeds {MAX_MODELS} items"
        )
    models: list[ModelCatalogEntry] = []
    controls: list[NativeControl] = []
    revision_rows: list[JsonObject] = []
    for alias_value, raw_model in model_table.items():
        alias = _FIELDS.required_text(alias_value, field="model alias")
        if not isinstance(raw_model, dict):
            raise KimiCatalogProtocolError(
                f"Kimi catalog model {alias!r} must be an object"
            )
        provider_ref = _FIELDS.required_text(
            raw_model.get("provider"), field=f"{alias}.provider"
        )
        if provider_ref not in providers:
            raise KimiCatalogProtocolError(
                f"Kimi catalog model {alias!r} names an unknown provider"
            )
        if not isinstance(providers[provider_ref], dict):
            raise KimiCatalogProtocolError(
                f"Kimi catalog provider {provider_ref!r} must be an object"
            )
        wire_model = _FIELDS.required_text(
            raw_model.get("model"), field=f"{alias}.model"
        )
        capabilities = _string_list(
            raw_model.get("capabilities"),
            field=f"{alias}.capabilities",
            limit=MAX_CAPABILITIES,
        )
        entry_id = local_id(f"{key.provider_id}:{key.execution_mode}:model", alias)
        display_name = display_text(raw_model.get("displayName"), alias)
        control = _thinking_control(
            raw_model,
            key=key,
            entry_id=entry_id,
            display_name=display_name,
        )
        if control is not None:
            controls.append(control)
            if len(controls) > MAX_CONTROLS:
                raise KimiCatalogProtocolError(
                    f"Kimi catalog exceeds {MAX_CONTROLS} native controls"
                )
        models.append(
            ModelCatalogEntry(
                entry_id=entry_id,
                provider_value=alias,
                display_name=display_name,
                capabilities=capabilities,
                native_control_ids=(control.control_id,) if control is not None else (),
            )
        )
        revision_rows.append(
            {
                "alias": alias,
                "provider": provider_ref,
                "wire_model": wire_model,
                "capabilities": list(capabilities),
                "native_control_ids": (
                    [control.control_id] if control is not None else []
                ),
            }
        )
    now = (checked_at or datetime.now(UTC)).astimezone(UTC)
    if not models:
        return ProviderCatalog(
            key=key,
            state=CatalogState(
                status=CatalogStatus.UNAVAILABLE,
                checked_at=now,
                reason="Kimi CLI has no configured model aliases",
            ),
            models=(),
        )
    normalized_models = tuple(models)
    normalized_controls = tuple(controls)
    return ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=now,
            revision=_revision(key, tuple(revision_rows), normalized_controls),
            expires_at=now + _CATALOG_TTL,
        ),
        models=normalized_models,
        native_controls=normalized_controls,
    )


async def _read_bounded(
    stream: asyncio.StreamReader | None,
    process: asyncio.subprocess.Process,
    metadata: Mapping[str, object] | None,
    output_budget: OutputBudget,
) -> bytes:
    if stream is None:
        return b""
    body = bytearray()
    while chunk := await stream.read(65_536):
        try:
            output_budget.charge(len(chunk))
        except KimiCatalogProtocolError:
            await kill_process_tree(process, metadata)
            raise
        body.extend(chunk)
    return bytes(body)


async def discover_kimi_catalog(
    command_prefix: tuple[str, ...],
    *,
    env: Mapping[str, str],
    cwd: str,
    key: ProviderCatalogKey,
    timeout: float = 30.0,
    metadata: Mapping[str, object] | None = None,
) -> KimiCatalogDiscovery:
    """Run the fixed prompt-free provider-list command and reap its process tree."""
    if not command_prefix:
        raise ValueError("command_prefix must not be empty")
    command = [*command_prefix, "provider", "list", "--json"]
    process = await spawn_acp_process(
        command, dict(env), cwd, use_exec=False, metadata=metadata
    )
    output_budget = OutputBudget(_protocol_error)
    stdout_task = asyncio.create_task(
        _read_bounded(process.stdout, process, metadata, output_budget)
    )
    stderr_task = asyncio.create_task(
        _read_bounded(process.stderr, process, metadata, output_budget)
    )
    outcome: KimiCatalogDiscovery | None = None
    failure: BaseException | None = None
    try:
        returncode, stdout, _ = await asyncio.wait_for(
            asyncio.gather(process.wait(), stdout_task, stderr_task),
            timeout=timeout,
        )
        if returncode != 0:
            raise KimiCatalogProtocolError("Kimi provider-list discovery failed")
        try:
            result = _JSON_OBJECT.validate_json(stdout)
        except (ValidationError, UnicodeDecodeError):
            raise KimiCatalogProtocolError(
                "Kimi provider-list discovery returned malformed JSON"
            ) from None
        outcome = KimiCatalogDiscovery(
            catalog=catalog_from_provider_list(result, key=key)
        )
    except BaseException as exc:
        failure = exc

    cleanup_steps: list[CleanupStep] = []
    if process.stdin is not None:
        cleanup_steps.append(("kimi-catalog-stdin", process.stdin.close))
    cleanup_steps.extend(
        [
            ("kimi-catalog-process", lambda: kill_process_tree(process, metadata)),
            ("kimi-catalog-stdout", lambda: cancel_task(stdout_task)),
            ("kimi-catalog-stderr", lambda: cancel_task(stderr_task)),
        ]
    )
    cleanup_failures = await run_independent_cleanups(*cleanup_steps)
    if failure is not None:
        output_failure = next(
            (
                exc
                for _, exc in cleanup_failures
                if isinstance(exc, KimiCatalogProtocolError)
            ),
            None,
        )
        if output_failure is not None:
            output_failure.add_note(
                f"Kimi discovery also failed with {type(failure).__name__}"
            )
            raise output_failure
        if cleanup_failures:
            failure.add_note(
                "Kimi catalog cleanup also failed: "
                + ", ".join(name for name, _ in cleanup_failures)
            )
        raise failure
    if cleanup_failures:
        raise RuntimeError(
            "Kimi catalog cleanup failed: "
            + ", ".join(name for name, _ in cleanup_failures)
        )
    if outcome is None:
        raise RuntimeError("Kimi catalog discovery completed without an outcome")
    return outcome
