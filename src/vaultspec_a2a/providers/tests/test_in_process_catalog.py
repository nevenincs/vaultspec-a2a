"""Real-composition proofs for serving the in-process provider lanes.

The lanes exist so a certification run can freeze a provider that cannot spend.
That is only true if the whole chain holds - serving policy, catalog shape,
admission, health derivation, selection freezing, and construction - so the
central test here drives that chain end to end through the production seams
rather than asserting on any one link in isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ...graph.enums import MODEL_MAP, Provider
from ..deterministic_chat_model import DeterministicResearchAdrChatModel
from ..factory import ProviderFactory, _discover_in_process_catalog
from ..in_process_catalog import (
    IN_PROCESS_EXECUTION_MODES,
    build_in_process_catalog,
    in_process_catalog_key,
    in_process_lane_serving_armed,
    served_in_process_lanes,
)
from ..lane_admission import (
    IN_PROCESS_CATALOG_LANES,
    PROVEN_CATALOG_TURN_LANES,
    catalog_lane_admission_reason,
    is_catalog_lane_admissible,
)
from ..mock_chat_model import MockChatModel
from ..provider_catalog import (
    AuthenticationState,
    CatalogStatus,
    ProviderCatalogKey,
    ProviderRecord,
    SelectionReference,
)
from ..provider_catalog_service import _DISPLAY_NAMES, _health_for
from ..team_selection import freeze_team_selection

if TYPE_CHECKING:
    from pathlib import Path

_DETERMINISTIC = in_process_catalog_key(Provider.DETERMINISTIC)
_MOCK = in_process_catalog_key(Provider.MOCK)


# -- serving policy -----------------------------------------------------------


def test_nothing_is_served_until_a_deployment_arms_it() -> None:
    """Hidden is the default posture, so no product deployment offers these."""
    assert served_in_process_lanes(armed=False, mock_api_base=None) == ()
    assert served_in_process_lanes(armed=False, mock_api_base="http://host:8100") == ()


def test_arming_serves_the_deterministic_lane_alone_without_a_tape_server() -> None:
    """The mock lane proxies HTTP, so it is withheld until it has somewhere to go."""
    assert served_in_process_lanes(armed=True, mock_api_base=None) == (_DETERMINISTIC,)
    assert served_in_process_lanes(armed=True, mock_api_base="   ") == (_DETERMINISTIC,)


def test_a_configured_tape_server_additionally_serves_the_mock_lane() -> None:
    assert served_in_process_lanes(
        armed=True, mock_api_base="http://localhost:8100"
    ) == (_DETERMINISTIC, _MOCK)


@pytest.mark.parametrize("value", ("1", "true", "TRUE", "yes", "on"))
def test_the_environment_declaration_arms_serving(value: str) -> None:
    assert in_process_lane_serving_armed({"VAULTSPEC_SERVE_IN_PROCESS_LANES": value})


@pytest.mark.parametrize("value", ("", "0", "false", "no", " ", "maybe"))
def test_anything_but_an_explicit_declaration_leaves_the_lanes_hidden(
    value: str,
) -> None:
    assert not in_process_lane_serving_armed(
        {"VAULTSPEC_SERVE_IN_PROCESS_LANES": value}
    )


def test_an_absent_declaration_leaves_the_lanes_hidden() -> None:
    assert not in_process_lane_serving_armed({})


# -- catalog shape ------------------------------------------------------------


@pytest.mark.parametrize("key", (_DETERMINISTIC, _MOCK))
def test_the_static_catalog_carries_everything_a_selection_revalidates(
    key: ProviderCatalogKey,
) -> None:
    """Available, revisioned, bounded-expiry, non-empty - the selectable shape."""
    before = datetime.now(UTC)
    catalog = build_in_process_catalog(key)

    assert catalog.key == key
    assert catalog.state.status is CatalogStatus.AVAILABLE
    assert catalog.state.revision
    assert catalog.state.expires_at is not None
    assert catalog.state.expires_at > before
    assert catalog.models


@pytest.mark.parametrize("key", (_DETERMINISTIC, _MOCK))
def test_entries_advertise_only_selectors_the_executor_answers_to(
    key: ProviderCatalogKey,
) -> None:
    """The served values come from the shared map, never a second declaration."""
    catalog = build_in_process_catalog(key)
    provider = Provider(key.provider_id)

    served = {model.provider_value for model in catalog.models}
    assert served == set(MODEL_MAP[provider].values())
    assert len({model.entry_id for model in catalog.models}) == len(catalog.models)


def test_the_revision_is_stable_across_builds() -> None:
    """A static catalog that re-revisioned would invalidate every live selection."""
    first = build_in_process_catalog(_DETERMINISTIC)
    second = build_in_process_catalog(_DETERMINISTIC)

    assert first.state.revision == second.state.revision


def test_each_lane_gets_its_own_revision_and_entry_ids() -> None:
    deterministic = build_in_process_catalog(_DETERMINISTIC)
    mock = build_in_process_catalog(_MOCK)

    assert deterministic.state.revision != mock.state.revision
    assert not {model.entry_id for model in deterministic.models} & {
        model.entry_id for model in mock.models
    }


@pytest.mark.parametrize(
    "key",
    (
        ProviderCatalogKey("deterministic", "openai-api"),
        ProviderCatalogKey("mock", "codex-app-server"),
        ProviderCatalogKey("claude", "in-process-deterministic"),
        ProviderCatalogKey("not-a-provider", "in-process-deterministic"),
    ),
)
def test_building_refuses_a_lane_identity_it_does_not_declare(
    key: ProviderCatalogKey,
) -> None:
    """Identity is the pair; an in-process provider under a foreign mode is not it."""
    with pytest.raises(ValueError, match="in-process provider lane"):
        build_in_process_catalog(key)


# -- admission ----------------------------------------------------------------


@pytest.mark.parametrize("key", (_DETERMINISTIC, _MOCK))
def test_the_declared_in_process_lanes_are_admitted(key: ProviderCatalogKey) -> None:
    assert key in IN_PROCESS_CATALOG_LANES
    assert is_catalog_lane_admissible(key)
    assert catalog_lane_admission_reason(key) is None


@pytest.mark.parametrize(
    "key",
    (
        ProviderCatalogKey("deterministic", "openai-api"),
        ProviderCatalogKey("mock", "kimi-code-acp"),
        ProviderCatalogKey("claude", "claude-agent-acp:node"),
        ProviderCatalogKey("kimi", "kimi-code-acp"),
        ProviderCatalogKey("openai", "openai-api"),
        ProviderCatalogKey("invented", "invented-mode"),
    ),
)
def test_serving_the_in_process_lanes_did_not_widen_admission(
    key: ProviderCatalogKey,
) -> None:
    """Deny stays the default: an unlisted lane is refused with a stated reason."""
    assert not is_catalog_lane_admissible(key)
    reason = catalog_lane_admission_reason(key)
    assert reason is not None
    assert "completed-turn proof" in reason


def test_the_external_proof_declaration_is_untouched() -> None:
    """In-process admission is a sibling declaration, never an entry in the proofs."""
    assert not IN_PROCESS_CATALOG_LANES & set(PROVEN_CATALOG_TURN_LANES)
    assert set(PROVEN_CATALOG_TURN_LANES) == {
        ProviderCatalogKey("codex", "codex-app-server")
    }


# -- the whole chain ----------------------------------------------------------


@pytest.mark.asyncio
async def test_the_deterministic_lane_is_reachable_through_the_real_registration(
    tmp_path: Path,
) -> None:
    """Arming actually reaches the factory's registry, not just the policy helper.

    This is the lane the certification stack freezes, so its presence in the real
    registration list - resolved by exact key, discovered through the registered
    callback - is the fact the six executing scenarios depend on.
    """
    registration = ProviderFactory().catalog_registration(
        _DETERMINISTIC, tmp_path, serve_in_process_lanes=True
    )
    discovery = await registration.discover()

    assert discovery.catalog.key == _DETERMINISTIC
    assert discovery.catalog.state.status is CatalogStatus.AVAILABLE
    assert discovery.catalog.models


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected_model"),
    (
        (_DETERMINISTIC, DeterministicResearchAdrChatModel),
        (_MOCK, MockChatModel),
    ),
)
async def test_an_in_process_lane_is_selectable_freezable_and_constructible(
    key: ProviderCatalogKey, expected_model: type
) -> None:
    """Drive discovery -> health -> freeze -> construction, for real.

    Every stage is the production one: the factory's own discovery adapter, the
    service's own health derivation, the real selection freezer, and the real
    construction path. The point of running them together is that a broken link
    anywhere - an unadmitted key, a health axis that never reaches available, an
    execution mode the factory refuses - fails here rather than surfacing as a
    skipped certification run.

    Discovery is driven through the adapter rather than a registration because
    the mock lane's registration additionally requires a configured tape server;
    that gating is a serving-policy fact, proven above, not a selection fact.
    """
    discovery = await _discover_in_process_catalog(key)

    assert discovery.authentication is AuthenticationState.NOT_APPLICABLE
    assert discovery.catalog.state.status is CatalogStatus.AVAILABLE

    health = _health_for(
        key,
        discovery.catalog,
        discovery.authentication,
        discovery.configured,
        discovery.transport,
    )
    assert health.selectable, health.reasons
    assert health.reasons == ()

    record = ProviderRecord(
        provider_id=key.provider_id,
        display_name=_DISPLAY_NAMES[Provider(key.provider_id)],
        execution_mode=key.execution_mode,
        health=health,
        catalog=discovery.catalog,
    )
    entry = discovery.catalog.models[0]
    frozen = freeze_team_selection(
        selection=SelectionReference(
            provider_id=key.provider_id,
            execution_mode=key.execution_mode,
            catalog_revision=discovery.catalog.state.revision or "",
            entry_id=entry.entry_id,
        ),
        overrides={},
        fallbacks=(),
        required_roles=("mock-coder-success",),
        records=(record,),
    )

    compiled = frozen.compiler_map()["mock-coder-success"]
    assert compiled["provider"] == key.provider_id
    assert compiled["execution_mode"] == key.execution_mode
    assert compiled["model_name"] == entry.provider_value

    model = ProviderFactory().create(
        Provider(compiled["provider"]),
        model=compiled["model_name"],
        execution_mode=compiled["execution_mode"],
    )
    assert isinstance(model, expected_model)


@pytest.mark.parametrize("provider", tuple(IN_PROCESS_EXECUTION_MODES))
def test_construction_refuses_an_in_process_lane_under_a_foreign_mode(
    provider: Provider,
) -> None:
    """The frozen mode is checked, so a mode the catalog never served cannot run."""
    with pytest.raises(ValueError, match="cannot execute mode"):
        ProviderFactory().create(provider, execution_mode="codex-app-server")


def test_unarmed_registrations_offer_no_in_process_lane(tmp_path: Path) -> None:
    """The registry a product deployment builds contains no in-process lane."""
    registrations = ProviderFactory().catalog_registrations(
        tmp_path, serve_in_process_lanes=False
    )

    served = {registration.key for registration in registrations}
    assert not served & IN_PROCESS_CATALOG_LANES
    with pytest.raises(ValueError, match="no catalog registration exists"):
        ProviderFactory().catalog_registration(
            _DETERMINISTIC, tmp_path, serve_in_process_lanes=False
        )


def test_arming_appends_without_reordering_the_external_lanes(tmp_path: Path) -> None:
    """A client enumerating external lanes sees them unchanged when arming flips."""
    factory = ProviderFactory()
    unarmed = factory.catalog_registrations(tmp_path, serve_in_process_lanes=False)
    armed = factory.catalog_registrations(tmp_path, serve_in_process_lanes=True)

    assert [item.key for item in armed[: len(unarmed)]] == [
        item.key for item in unarmed
    ]
    assert {item.key for item in armed[len(unarmed) :]} <= IN_PROCESS_CATALOG_LANES
