"""A2A's opinionated default names a served entry and never a model.

The catalog contract removed implicit provider defaults, which left a first-run
user facing a list with nothing chosen. The recommendation closes that gap, and
these pin the two properties that keep it from reintroducing what was removed: it
always names an entry the SAME lane advertises, and it is a rule over what a lane
says rather than a mapping onto model names or size tiers.

Every catalog here is a real ``ProviderCatalog`` built through its own validating
constructor, and the projection is the real response DTO the gateway serves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ...api.schemas.provider_catalog import ProviderCatalogResponse
from ..catalog_recommendation import recommended_entry_id
from ..provider_catalog import (
    AdmissionState,
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    HealthState,
    ModelCatalogEntry,
    ProviderCatalog,
    ProviderCatalogKey,
    ProviderRecord,
    StructuredProviderHealth,
)

_KEY = ProviderCatalogKey(provider_id="probe", execution_mode="probe-mode")
_CHECKED = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _catalog(*models: ModelCatalogEntry) -> ProviderCatalog:
    status = CatalogStatus.AVAILABLE if models else CatalogStatus.UNAVAILABLE
    return ProviderCatalog(
        key=_KEY,
        state=CatalogState(status=status, checked_at=_CHECKED, revision="rev-1"),
        models=models,
    )


def _entry(entry_id: str, *capabilities: str) -> ModelCatalogEntry:
    return ModelCatalogEntry(
        entry_id=entry_id,
        provider_value=f"value-for-{entry_id}",
        display_name=entry_id.replace("-", " ").title(),
        capabilities=capabilities,
    )


def test_an_empty_lane_has_nothing_to_recommend() -> None:
    """A lane advertising no entry recommends none, rather than inventing one.

    The distinction a client needs is "we have an opinion" versus "there is
    nothing to have an opinion about"; collapsing them would make an unavailable
    lane look pre-selected.
    """
    assert recommended_entry_id(_catalog()) is None


def test_the_lanes_own_ordering_decides_when_it_declares_nothing() -> None:
    """With no capability vocabulary to read, the provider's order wins.

    Falling back to the lane's own first entry keeps the opinion inside what the
    provider said. Any other ranking would be a judgement about models this
    module is specifically built not to make.
    """
    catalog = _catalog(_entry("first"), _entry("second"), _entry("third"))
    assert recommended_entry_id(catalog) == "first"


def test_a_declared_reasoning_entry_outranks_mere_position() -> None:
    """A lane that marks an entry reasoning-grade gets that entry recommended.

    This is the rule doing real work: the preferred entry is second in the
    provider's own ordering, so a position-only rule would miss it, and the
    capability string is the closest a lane comes to naming its best entry.
    """
    catalog = _catalog(_entry("fast"), _entry("deep", "reasoning"), _entry("other"))
    assert recommended_entry_id(catalog) == "deep"


def test_the_recommendation_is_never_a_model_name() -> None:
    """The rule reads capabilities and order - never a model identifier.

    Read from the SOURCE rather than asserted about behaviour: a name-based
    default is invisible to any input-driven test that does not happen to use
    that name, and the constraint being defended is that no external model
    identifier appears in production source at all.
    """
    source = (
        Path(__file__).resolve().parents[1] / "catalog_recommendation.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("gpt-", "claude-", "gemini-", "sonnet", "opus", "kimi-", "glm-"):
        assert forbidden not in source.lower(), (
            f"the recommendation rule names {forbidden!r}; a model-name default "
            "goes stale the moment a provider ships a new one"
        )


def test_the_served_recommendation_names_a_served_entry() -> None:
    """Through the real response DTO, the recommendation is selectable as-is.

    The point of serving it is that a client can pre-select it without a second
    lookup, which only holds if the id appears among the entries served beside
    it in the same lane.
    """
    catalog = _catalog(_entry("fast"), _entry("deep", "reasoning"))
    record = ProviderRecord(
        provider_id=_KEY.provider_id,
        display_name="Probe",
        execution_mode=_KEY.execution_mode,
        health=StructuredProviderHealth(
            configured=HealthState.AVAILABLE,
            transport=HealthState.AVAILABLE,
            authentication=AuthenticationState.AUTHENTICATED,
            catalog=CatalogStatus.AVAILABLE,
            admission=AdmissionState.ADMITTED,
            selectable=True,
            reasons=(),
            checked_at=_CHECKED,
        ),
        catalog=catalog,
    )

    served = ProviderCatalogResponse.from_records((record,)).providers[0].catalog

    assert served.recommended_entry_id == "deep"
    assert served.recommended_entry_id in {model.entry_id for model in served.models}
