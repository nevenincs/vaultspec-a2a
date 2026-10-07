"""Real-composition proofs for serving the in-process provider lanes.

The lanes exist so a certification run can freeze a provider that cannot spend.
That is only true if the whole chain holds - the lane-plugin seam, serving
policy, catalog shape, admission, health derivation, selection freezing, and
construction - so the central test here drives that chain end to end through the
production seams rather than asserting on any one link in isolation. Every test
holds the deterministic lane through its real plugin, exactly as a source-run
gateway does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ...control.config import Settings
from ...graph.enums import Provider
from ...testing import armed_desktop_app_home, armed_environment, settings_override
from ...testing.lanes import (
    DETERMINISTIC_LANE,
    DeterministicResearchAdrChatModel,
    seated_lanes,
)
from ..factory import ProviderFactory, _discover_in_process_catalog
from ..in_process_catalog import (
    BUILT_IN_LANES,
    build_in_process_catalog,
    discover_in_process_catalog,
    in_process_catalog_key,
    in_process_lane,
    in_process_lanes,
    served_in_process_lanes,
)
from ..lane_admission import (
    PROVEN_CATALOG_TURN_LANES,
    catalog_lane_admission_reason,
    is_catalog_lane_admissible,
)
from ..lane_registry import LanePluginError, LaneRegistration
from ..mock_chat_model import MockChatModel
from ..provider_catalog import (
    AuthenticationState,
    CatalogStatus,
    ProviderCatalogKey,
    ProviderRecord,
    SelectionReference,
)
from ..provider_catalog_service import (
    _health_for,
    stamp_catalog_expiry,
)
from ..team_selection import freeze_team_selection

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_MOCK_LANE = next(lane for lane in BUILT_IN_LANES if lane.provider is Provider.MOCK)
_LANES: tuple[LaneRegistration, ...] = (DETERMINISTIC_LANE, _MOCK_LANE)
_DETERMINISTIC = in_process_catalog_key(DETERMINISTIC_LANE)
_MOCK = in_process_catalog_key(_MOCK_LANE)


@pytest.fixture(autouse=True)
def _held_lanes() -> Iterator[None]:
    with seated_lanes():
        yield


def _held_keys() -> set[ProviderCatalogKey]:
    return {in_process_catalog_key(lane) for lane in in_process_lanes()}


# -- the lane-plugin seam -----------------------------------------------------


def test_the_plugin_lane_is_held_beside_the_built_in_lanes() -> None:
    """Plugin lanes come first, then the lanes the build compiles in."""
    assert in_process_lanes() == (DETERMINISTIC_LANE, *BUILT_IN_LANES)
    assert in_process_lane(Provider.DETERMINISTIC) is DETERMINISTIC_LANE


def test_without_a_plugin_the_lane_is_not_held() -> None:
    """Nothing in the product names the lane; only its plugin brings it."""
    with settings_override(lane_plugins=()):
        assert in_process_lane(Provider.DETERMINISTIC) is None
        assert _DETERMINISTIC not in _held_keys()
        assert not is_catalog_lane_admissible(_DETERMINISTIC)
        with pytest.raises(ValueError, match="Unsupported provider"):
            ProviderFactory().create(Provider.DETERMINISTIC, model="deterministic")


def test_a_plugin_named_while_the_lanes_are_unarmed_refuses_the_process() -> None:
    with (
        settings_override(serve_in_process_lanes=False),
        pytest.raises(LanePluginError, match="honoured only while"),
    ):
        ProviderFactory()


def test_a_plugin_named_under_the_desktop_profile_refuses_the_process(
    tmp_path: Path,
) -> None:
    with (
        armed_desktop_app_home(tmp_path),
        pytest.raises(LanePluginError, match="desktop profile"),
    ):
        in_process_lanes()


@pytest.mark.parametrize(
    ("module", "reason"),
    (
        ("vaultspec_a2a.testing.lanes.absent", "cannot be imported"),
        ("vaultspec_a2a.testing.environment", "exposes no register_lanes"),
    ),
)
def test_a_plugin_that_cannot_register_refuses_the_process(
    module: str, reason: str
) -> None:
    with (
        settings_override(lane_plugins=(module,)),
        pytest.raises(LanePluginError, match=reason),
    ):
        in_process_lanes()


def _plugins_from(value: str | None) -> tuple[str, ...]:
    """Read the plugin list the way the service does: from a fresh settings object."""
    with armed_environment(VAULTSPEC_A2A_LANE_PLUGINS=value):
        return Settings().lane_plugins


def test_the_plugin_list_is_read_as_comma_separated_module_paths() -> None:
    assert _plugins_from(None) == ()
    assert _plugins_from("") == ()
    assert _plugins_from("pkg.one, pkg.two,pkg.one") == ("pkg.one", "pkg.two")


@pytest.mark.parametrize("value", ("pkg.one,,pkg.two", "pkg one", "pkg.1st"))
def test_a_malformed_plugin_list_is_refused_rather_than_guessed(value: str) -> None:
    with pytest.raises(ValidationError, match="lane_plugins"):
        _plugins_from(value)


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


def _armed_by(value: str | None) -> bool:
    """Read the arming the way the service does: from a fresh settings object."""
    with armed_environment(VAULTSPEC_A2A_SERVE_IN_PROCESS_LANES=value):
        return Settings().serve_in_process_lanes


@pytest.mark.parametrize("value", ("1", "true", "TRUE", "yes", "on"))
def test_the_environment_declaration_arms_serving(value: str) -> None:
    assert _armed_by(value)


@pytest.mark.parametrize("value", ("", "0", "false", "no", "off"))
def test_a_negative_or_blank_declaration_leaves_the_lanes_hidden(value: str) -> None:
    assert not _armed_by(value)


def test_an_unreadable_declaration_is_refused_rather_than_guessed() -> None:
    """A typo must not silently leave a deployment's lanes hidden or served."""
    with pytest.raises(ValidationError, match="serve_in_process_lanes"):
        _armed_by("maybe")


def test_an_absent_declaration_leaves_the_lanes_hidden() -> None:
    assert not _armed_by(None)


# -- catalog shape ------------------------------------------------------------


@pytest.mark.parametrize("lane", _LANES)
def test_the_static_catalog_carries_everything_a_selection_revalidates(
    lane: LaneRegistration,
) -> None:
    """Available, revisioned, non-empty, and bounded once the service stamps it."""
    before = datetime.now(UTC)
    catalog = build_in_process_catalog(lane)

    assert catalog.key == in_process_catalog_key(lane)
    assert catalog.state.status is CatalogStatus.AVAILABLE
    assert catalog.state.revision
    assert catalog.state.expires_at is None
    assert catalog.models

    stamped = stamp_catalog_expiry(catalog)
    assert stamped.state.expires_at is not None
    assert stamped.state.expires_at > before
    assert stamped.state.revision == catalog.state.revision
    assert stamped.models == catalog.models


@pytest.mark.parametrize("lane", _LANES)
def test_entries_advertise_only_selectors_the_executor_answers_to(
    lane: LaneRegistration,
) -> None:
    """The catalog serves the exact selectors its in-process executor implements."""
    catalog = build_in_process_catalog(lane)

    served = {model.provider_value for model in catalog.models}
    assert served == set(lane.model_values)
    assert len({model.entry_id for model in catalog.models}) == len(catalog.models)


def test_the_revision_is_stable_across_builds() -> None:
    """A static catalog that re-revisioned would invalidate every live selection."""
    first = build_in_process_catalog(DETERMINISTIC_LANE)
    second = build_in_process_catalog(DETERMINISTIC_LANE)

    assert first.state.revision == second.state.revision


def test_each_lane_gets_its_own_revision_and_entry_ids() -> None:
    deterministic = build_in_process_catalog(DETERMINISTIC_LANE)
    mock = build_in_process_catalog(_MOCK_LANE)

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
def test_discovery_refuses_a_lane_identity_it_does_not_hold(
    key: ProviderCatalogKey,
) -> None:
    """Identity is the pair; an in-process provider under a foreign mode is not it."""
    with pytest.raises(ValueError, match="in-process provider lane"):
        discover_in_process_catalog(key)


# -- admission ----------------------------------------------------------------


@pytest.mark.parametrize("key", (_DETERMINISTIC, _MOCK))
def test_the_held_in_process_lanes_are_admitted(key: ProviderCatalogKey) -> None:
    assert key in _held_keys()
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
    """In-process admission is a sibling source, never an entry in the proofs."""
    assert not _held_keys() & set(PROVEN_CATALOG_TURN_LANES)
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
    ("lane", "expected_model"),
    (
        (DETERMINISTIC_LANE, DeterministicResearchAdrChatModel),
        (_MOCK_LANE, MockChatModel),
    ),
)
async def test_an_in_process_lane_is_selectable_freezable_and_constructible(
    lane: LaneRegistration, expected_model: type
) -> None:
    """Drive discovery -> health -> freeze -> construction, for real.

    Every stage is the production one: the factory's own discovery adapter, the
    service's own health derivation and expiry stamp, the real selection freezer,
    and the real construction path. The point of running them together is that a
    broken link anywhere - an unadmitted key, a health axis that never reaches
    available, an execution mode the factory refuses - fails here rather than
    surfacing as a skipped certification run.

    Discovery is driven through the adapter rather than a registration because
    the mock lane's registration additionally requires a configured tape server;
    that gating is a serving-policy fact, proven above, not a selection fact.
    """
    key = in_process_catalog_key(lane)
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
        display_name=lane.display_name,
        execution_mode=key.execution_mode,
        health=health,
        catalog=stamp_catalog_expiry(discovery.catalog),
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
    assert compiled.provider_id.value == key.provider_id
    assert compiled.execution_mode == key.execution_mode
    assert compiled.model_name == entry.provider_value

    model = ProviderFactory().create(
        compiled.provider_id,
        model=compiled.model_name,
        execution_mode=compiled.execution_mode,
    )
    assert isinstance(model, expected_model)


@pytest.mark.parametrize("lane", _LANES)
def test_construction_refuses_an_in_process_lane_under_a_foreign_mode(
    lane: LaneRegistration,
) -> None:
    """The frozen mode is checked, so a mode the catalog never served cannot run."""
    with pytest.raises(ValueError, match="cannot execute mode"):
        ProviderFactory().create(
            lane.provider,
            model=lane.model_values[0],
            execution_mode="codex-app-server",
        )


def test_unarmed_registrations_offer_no_in_process_lane(tmp_path: Path) -> None:
    """The registry a product deployment builds contains no in-process lane."""
    registrations = ProviderFactory().catalog_registrations(
        tmp_path, serve_in_process_lanes=False
    )

    served = {registration.key for registration in registrations}
    assert not served & _held_keys()
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
    assert {item.key for item in armed[len(unarmed) :]} <= _held_keys()
