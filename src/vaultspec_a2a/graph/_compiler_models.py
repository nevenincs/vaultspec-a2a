"""Resolving one run's models from its exact catalog-frozen assignment.

A run is compiled against the lanes it was admitted with, not against whatever
the catalogs say at compile time. That makes this a parsing and validation
concern rather than a wiring one: every function here reads a frozen schema-v1
record, refuses it on any divergence, and only then asks the provider factory
for a model.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast

from ..providers.cli_resolution import (
    ProviderRuntimeUnavailableError,
    ProviderRuntimeUnavailableReason,
)
from ..providers.factory import (
    validate_current_execution_lane,
    validate_current_native_controls,
)
from ..providers.lane_admission import catalog_lane_admission_reason
from ..providers.provider_catalog import ProviderCatalogKey
from .enums import Provider

if TYPE_CHECKING:
    from pathlib import Path

    # Annotation-only: importing langchain_core.language_models at module scope
    # costs seconds (it eagerly probes for transformers), and this module only
    # names BaseChatModel in signatures - the instances it returns come from the
    # provider factory, which imports the model stack at construction time.
    from langchain_core.language_models import BaseChatModel

    from .protocols import ProviderFactoryProtocol

__all__ = [
    "parse_catalog_preferences",
    "resolve_model_for_worker",
    "resolve_supervisor_model",
    "validate_frozen_assignment_inventory",
]

logger = logging.getLogger(__name__)


def _require_current_frozen_lane_proof(provider: Provider, execution_mode: str) -> None:
    reason = catalog_lane_admission_reason(
        ProviderCatalogKey(provider.value, execution_mode)
    )
    if reason is not None:
        raise ProviderRuntimeUnavailableError(
            reason, reason=ProviderRuntimeUnavailableReason.TURN_PROOF_MISSING
        )


class _ModelResolutionOptional(TypedDict, total=False):
    frozen_assignment: dict[str, dict[str, Any]] | None


class _ModelResolutionArgs(_ModelResolutionOptional):
    provider_factory: ProviderFactoryProtocol


def resolve_model_for_worker(
    worker_ref: Any,
    agent_config: Any,
    team_config: Any,
    workspace_root: Path | None = None,
    **kwargs: Unpack[_ModelResolutionArgs],
) -> tuple[BaseChatModel, Provider, str]:
    """Construct a worker only from an exact catalog-frozen assignment."""
    del team_config
    provider_factory = kwargs["provider_factory"]
    frozen_assignment = kwargs.get("frozen_assignment")
    frozen = (frozen_assignment or {}).get(worker_ref.agent_id)
    if frozen is None or frozen.get("schema_version") != 1:
        raise ValueError(
            f"Worker {worker_ref.agent_id!r} has no exact catalog-frozen selection"
        )
    candidates = [frozen, *_catalog_fallbacks(frozen)]
    parsed_candidates = [
        parse_catalog_preferences(candidate) for candidate in candidates
    ]
    for provider, _model, execution_mode, _controls in parsed_candidates:
        validate_current_execution_lane(provider, execution_mode)
        validate_current_native_controls(provider, _controls)
    catalog_exc: Exception | None = None
    for provider, model_name, execution_mode, native_controls in parsed_candidates:
        try:
            _require_current_frozen_lane_proof(provider, execution_mode)
            model = provider_factory.create(
                provider,
                model=model_name,
                agent_config=agent_config,
                workspace_root=workspace_root,
                execution_mode=execution_mode,
                native_controls=native_controls,
            )
            return model, provider, model_name
        except ProviderRuntimeUnavailableError as exc:
            logger.warning(
                "Frozen provider lane %s/%s unavailable for worker %s: %s",
                provider.value,
                execution_mode,
                agent_config.id,
                exc,
            )
            catalog_exc = exc
    raise ValueError(
        f"All frozen provider lanes exhausted for worker {agent_config.id!r}"
    ) from catalog_exc


def _catalog_fallbacks(frozen: dict[str, Any]) -> list[dict[str, Any]]:
    raw_value: object = frozen.get("fallbacks")
    if not isinstance(raw_value, list):
        raise ValueError("Frozen catalog assignment has invalid fallbacks")
    raw = cast("list[object]", raw_value)
    if len(raw) > 8:
        raise ValueError("Frozen catalog assignment has invalid fallbacks")
    if not all(isinstance(item, dict) for item in raw):
        raise ValueError("Frozen catalog assignment has invalid fallbacks")
    return [cast("dict[str, Any]", item) for item in raw]


def _validate_catalog_assignment_shape(frozen: dict[str, Any]) -> None:
    primary_keys = {
        "provider",
        "execution_mode",
        "catalog_revision",
        "entry_id",
        "model_name",
        "controls",
        "fallbacks",
        "provenance",
        "schema_version",
    }
    fallback_keys = {
        "provider_id",
        "execution_mode",
        "catalog_revision",
        "entry_id",
        "model_name",
        "controls",
        "defaulted_control_ids",
        "schema_version",
        "provider_display_name",
        "model_display_name",
    }
    allowed = primary_keys if "provider" in frozen else fallback_keys
    required = (
        primary_keys
        if "provider" in frozen
        else fallback_keys - {"provider_display_name", "model_display_name"}
    )
    if set(frozen) - allowed or not required.issubset(frozen):
        raise ValueError("Frozen catalog assignment has invalid fields")
    if frozen.get("schema_version") != 1:
        raise ValueError("Frozen catalog assignment has an invalid schema_version")


def _native_control_entry(raw_control: object) -> tuple[str, str]:
    if not isinstance(raw_control, dict):
        raise ValueError("Frozen catalog assignment has invalid native controls")
    control = cast("dict[str, object]", raw_control)
    if set(control) - {
        "control_id",
        "option_id",
        "provider_value",
        "display_name",
        "option_display_name",
    } or not {"control_id", "option_id", "provider_value"}.issubset(control):
        raise ValueError("Frozen catalog assignment has invalid native controls")
    control_id = control.get("control_id")
    provider_value = control.get("provider_value")
    if (
        not isinstance(control_id, str)
        or not control_id
        or not isinstance(provider_value, str)
        or not provider_value
    ):
        raise ValueError("Frozen catalog assignment has invalid native controls")
    return control_id, provider_value


def _parse_native_controls(raw_controls_value: object) -> dict[str, str]:
    if not isinstance(raw_controls_value, list):
        raise ValueError("Frozen catalog assignment has invalid native controls")
    raw_controls = cast("list[object]", raw_controls_value)
    if len(raw_controls) > 32:
        raise ValueError("Frozen catalog assignment has invalid native controls")
    controls: dict[str, str] = {}
    for raw_control in raw_controls:
        control_id, provider_value = _native_control_entry(raw_control)
        if control_id in controls:
            raise ValueError("Frozen catalog assignment has invalid native controls")
        controls[control_id] = provider_value
    return controls


def parse_catalog_preferences(
    frozen: dict[str, Any],
) -> tuple[Provider, str, str, dict[str, str]]:
    """Parse one exact schema-v1 lane without consulting current catalogs."""
    _validate_catalog_assignment_shape(frozen)
    raw_provider = (
        frozen.get("provider") if "provider" in frozen else frozen.get("provider_id")
    )
    try:
        provider = Provider(raw_provider)
    except ValueError as exc:
        raise ValueError(
            f"Frozen catalog assignment has an invalid provider {raw_provider!r}"
        ) from exc
    model_name = frozen.get("model_name")
    execution_mode = frozen.get("execution_mode")
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("Frozen catalog assignment is missing its concrete model_name")
    if not isinstance(execution_mode, str) or not execution_mode.strip():
        raise ValueError("Frozen catalog assignment is missing its execution_mode")
    controls = _parse_native_controls(frozen.get("controls"))
    if "provenance" in frozen:
        provenance = frozen["provenance"]
        if not isinstance(provenance, dict):
            raise ValueError("Frozen catalog assignment has invalid provenance")
        provenance_dict = cast("dict[object, object]", provenance)
        if set(provenance_dict) != {"selection_source"}:
            raise ValueError("Frozen catalog assignment has invalid provenance")
    return provider, model_name, execution_mode, controls


def validate_frozen_assignment_inventory(
    frozen_assignment: dict[str, dict[str, Any]] | None,
) -> None:
    """Validate every frozen lane before compilation constructs any provider."""
    for frozen in (frozen_assignment or {}).values():
        candidates = [frozen, *_catalog_fallbacks(frozen)]
        for candidate in candidates:
            provider, _model, execution_mode, _controls = parse_catalog_preferences(
                candidate
            )
            validate_current_execution_lane(provider, execution_mode)
            validate_current_native_controls(provider, _controls)


def resolve_supervisor_model(
    workspace_root: Path | None = None,
    *,
    provider_factory: ProviderFactoryProtocol,
    supervisor_agent_config: Any | None = None,
    frozen_assignment: dict[str, dict[str, Any]] | None = None,
) -> tuple[BaseChatModel, Provider, str]:
    """Construct a supervisor from the run's exact team catalog selection."""
    frozen = (frozen_assignment or {}).get("__supervisor__")
    if frozen is None:
        raise ValueError("Supervisor has no exact catalog-frozen selection")
    provider, model_name, execution_mode, native_controls = parse_catalog_preferences(
        frozen
    )
    validate_current_execution_lane(provider, execution_mode)
    _require_current_frozen_lane_proof(provider, execution_mode)
    model = provider_factory.create(
        provider,
        model=model_name,
        agent_config=supervisor_agent_config,
        workspace_root=workspace_root,
        execution_mode=execution_mode,
        native_controls=native_controls,
    )
    return model, provider, model_name
