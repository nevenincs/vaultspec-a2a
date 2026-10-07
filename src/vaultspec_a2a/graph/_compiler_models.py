"""Resolving one run's models from its exact catalog-frozen assignment.

A run is compiled against the lanes it was admitted with, not against whatever
the catalogs say at compile time. Every lane arrives as a closed, typed frozen
lane; what is checked here is that the lane can still execute in this build - its
provider/mode pair, its native controls, and its completed-turn proof - before
the provider factory is asked for a model.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypedDict, Unpack

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

if TYPE_CHECKING:
    from pathlib import Path

    # Annotation-only: importing langchain_core.language_models at module scope
    # costs seconds (it eagerly probes for transformers), and this module only
    # names BaseChatModel in signatures - the instances it returns come from the
    # provider factory, which imports the model stack at construction time.
    from langchain_core.language_models import BaseChatModel

    from ..providers.team_selection import FrozenLaneAssignment
    from .enums import Provider
    from .protocols import ProviderFactoryProtocol

__all__ = [
    "resolve_model_for_worker",
    "resolve_supervisor_model",
    "validate_frozen_assignment_inventory",
]

logger = logging.getLogger(__name__)


def _require_current_lane(lane: FrozenLaneAssignment) -> None:
    validate_current_execution_lane(lane.provider_id, lane.execution_mode)
    validate_current_native_controls(lane.provider_id, lane.native_controls())


def _require_current_frozen_lane_proof(lane: FrozenLaneAssignment) -> None:
    reason = catalog_lane_admission_reason(
        ProviderCatalogKey(lane.provider_id.value, lane.execution_mode)
    )
    if reason is not None:
        raise ProviderRuntimeUnavailableError(
            reason, reason=ProviderRuntimeUnavailableReason.TURN_PROOF_MISSING
        )


def _create_frozen_model(
    lane: FrozenLaneAssignment,
    agent_config: Any,
    workspace_root: Path | None,
    provider_factory: ProviderFactoryProtocol,
) -> BaseChatModel:
    _require_current_frozen_lane_proof(lane)
    return provider_factory.create(
        lane.provider_id,
        model=lane.model_name,
        agent_config=agent_config,
        workspace_root=workspace_root,
        execution_mode=lane.execution_mode,
        native_controls=lane.native_controls(),
    )


class _ModelResolutionOptional(TypedDict, total=False):
    frozen_assignment: dict[str, FrozenLaneAssignment] | None


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
    frozen = (kwargs.get("frozen_assignment") or {}).get(worker_ref.agent_id)
    if frozen is None:
        raise ValueError(
            f"Worker {worker_ref.agent_id!r} has no exact catalog-frozen selection"
        )
    candidates = (frozen, *frozen.fallbacks)
    for candidate in candidates:
        _require_current_lane(candidate)
    catalog_exc: Exception | None = None
    for candidate in candidates:
        try:
            model = _create_frozen_model(
                candidate, agent_config, workspace_root, provider_factory
            )
            return model, candidate.provider_id, candidate.model_name
        except ProviderRuntimeUnavailableError as exc:
            logger.warning(
                "Frozen provider lane %s/%s unavailable for worker %s: %s",
                candidate.provider_id.value,
                candidate.execution_mode,
                agent_config.id,
                exc,
            )
            catalog_exc = exc
    raise ValueError(
        f"All frozen provider lanes exhausted for worker {agent_config.id!r}"
    ) from catalog_exc


def validate_frozen_assignment_inventory(
    frozen_assignment: dict[str, FrozenLaneAssignment] | None,
) -> None:
    """Validate every frozen lane before compilation constructs any provider."""
    for frozen in (frozen_assignment or {}).values():
        for candidate in (frozen, *frozen.fallbacks):
            _require_current_lane(candidate)


def resolve_supervisor_model(
    workspace_root: Path | None = None,
    *,
    provider_factory: ProviderFactoryProtocol,
    supervisor_agent_config: Any | None = None,
    frozen_assignment: dict[str, FrozenLaneAssignment] | None = None,
) -> tuple[BaseChatModel, Provider, str]:
    """Construct a supervisor from the run's exact team catalog selection."""
    frozen = (frozen_assignment or {}).get("__supervisor__")
    if frozen is None:
        raise ValueError("Supervisor has no exact catalog-frozen selection")
    _require_current_lane(frozen)
    model = _create_frozen_model(
        frozen, supervisor_agent_config, workspace_root, provider_factory
    )
    return model, frozen.provider_id, frozen.model_name
