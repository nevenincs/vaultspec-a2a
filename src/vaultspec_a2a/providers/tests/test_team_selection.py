"""Real domain-contract tests for explicit team selection admission."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from .._team_selection_record import frozen_team_selection_from_record
from ..provider_catalog import (
    AdmissionState,
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    ControlKind,
    ControlSelection,
    HealthState,
    ModelCatalogEntry,
    NativeControl,
    NativeControlOption,
    ProviderCatalog,
    ProviderCatalogKey,
    ProviderHealthAxes,
    ProviderRecord,
    SelectionReference,
    StructuredProviderHealth,
)
from ..team_selection import (
    TeamSelectionError,
    freeze_team_selection,
    normalize_replay_selection,
)

_CHECKED = datetime(2099, 1, 1, tzinfo=UTC)


def _record(
    *,
    expires_at: datetime | None = _CHECKED,
    status: CatalogStatus = CatalogStatus.AVAILABLE,
) -> ProviderRecord:
    key = ProviderCatalogKey(provider_id="codex", execution_mode="codex-app-server")
    catalog = ProviderCatalog(
        key=key,
        state=CatalogState(
            status=status,
            checked_at=datetime(2026, 1, 1, tzinfo=UTC),
            revision="rev-1",
            expires_at=expires_at,
        ),
        models=(
            ModelCatalogEntry(
                entry_id="entry-1",
                provider_value="gpt-exact",
                display_name="Exact",
                native_control_ids=("reasoning",),
            ),
        ),
        native_controls=(
            NativeControl(
                control_id="reasoning",
                kind=ControlKind.THOUGHT_LEVEL,
                display_name="Reasoning",
                options=(
                    NativeControlOption(
                        option_id="low",
                        provider_value="low",
                        display_name="Low",
                    ),
                    NativeControlOption(
                        option_id="high",
                        provider_value="high",
                        display_name="High",
                    ),
                ),
                default_option_id="low",
            ),
        ),
    )
    health = StructuredProviderHealth.derive(
        axes=ProviderHealthAxes(
            configured=HealthState.AVAILABLE,
            transport=HealthState.AVAILABLE,
            authentication=AuthenticationState.AUTHENTICATED,
            catalog=status,
            admission=AdmissionState.ADMITTED,
        ),
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return ProviderRecord(
        provider_id="codex",
        display_name="Codex",
        execution_mode="codex-app-server",
        health=health,
        catalog=catalog,
    )


def _selection(
    *,
    catalog_revision: str = "rev-1",
    entry_id: str = "entry-1",
    controls: tuple[ControlSelection, ...] = (),
) -> SelectionReference:
    return SelectionReference(
        schema_version=1,
        provider_id="codex",
        execution_mode="codex-app-server",
        catalog_revision=catalog_revision,
        entry_id=entry_id,
        controls=controls,
    )


def test_freeze_normalizes_authoritative_defaults_and_exact_model_value() -> None:
    frozen = freeze_team_selection(
        selection=_selection(),
        overrides={},
        fallbacks=(),
        required_roles=("coder", "reviewer"),
        records=(_record(),),
    )

    assert frozen.selection.reference.controls == (
        ControlSelection(control_id="reasoning", option_id="low"),
    )
    assert frozen.compiler_map()["coder"].model_name == "gpt-exact"
    assert frozen.to_record()["selection"]["controls"] == [
        {
            "control_id": "reasoning",
            "option_id": "low",
            "provider_value": "low",
            "display_name": "Reasoning",
            "option_display_name": "Low",
        }
    ]
    assert frozen.disclosure()["assignments"][0] == {
        "provider_id": "codex",
        "provider_display_name": "Codex",
        "execution_mode": "codex-app-server",
        "catalog_revision": "rev-1",
        "entry_id": "entry-1",
        "model_name": "gpt-exact",
        "model_display_name": "Exact",
        "controls": [
            {
                "control_id": "reasoning",
                "option_id": "low",
                "provider_value": "low",
                "display_name": "Reasoning",
                "option_display_name": "Low",
            }
        ],
        "role_id": "coder",
        "fallbacks": [],
        "provenance": {"selection_source": "team_selection"},
    }
    assert frozen_team_selection_from_record(frozen.to_record()) == frozen


def test_persisted_selection_refuses_tampered_provider_value() -> None:
    frozen = freeze_team_selection(
        selection=_selection(),
        overrides={},
        fallbacks=(),
        required_roles=("coder",),
        records=(_record(),),
    )
    record = frozen.to_record()
    record["selection"]["model_name"] = "tampered"

    with pytest.raises(TeamSelectionError, match="digest does not match"):
        frozen_team_selection_from_record(record)


@pytest.mark.parametrize(
    ("path", "field"),
    [
        ((), "profile_id"),
        (("selection",), "model_profile"),
        (("selection", "controls", 0), "profile_id"),
    ],
)
def test_persisted_selection_rejects_unknown_fields_without_digest_change(
    path: tuple[str | int, ...], field: str
) -> None:
    frozen = freeze_team_selection(
        selection=_selection(),
        overrides={},
        fallbacks=(),
        required_roles=("coder",),
        records=(_record(),),
    )
    record = frozen.to_record()
    original_digest = record["digest"]
    target: object = record
    for key in path:
        if isinstance(key, str):
            assert isinstance(target, dict)
            target = cast("dict[str, object]", target)[key]
        else:
            assert isinstance(target, list)
            target = cast("list[object]", target)[key]
    assert isinstance(target, dict)
    target[field] = "retired"
    assert record["digest"] == original_digest
    with pytest.raises(TeamSelectionError, match="persisted team selection is invalid"):
        frozen_team_selection_from_record(record)


def test_restart_refuses_any_retired_model_profile_state() -> None:
    import json

    from ...control.execution_authority import (
        ExecutionAuthorityError,
        ExecutionAuthorityFailure,
        resolve_execution_authority,
    )

    frozen = freeze_team_selection(
        selection=_selection(),
        overrides={},
        fallbacks=(),
        required_roles=("coder",),
        records=(_record(),),
    )
    with pytest.raises(ExecutionAuthorityError) as raised:
        resolve_execution_authority(
            json.dumps(
                {
                    "provider_catalog_selection": frozen.to_record(),
                    "model_profile": {"profile_id": "must-not-win", "roles": {}},
                }
            )
        )
    assert raised.value.reason is ExecutionAuthorityFailure.RETIRED


@pytest.mark.parametrize(
    ("selection", "reason"),
    [
        (_selection(catalog_revision="old"), "stale catalog revision"),
        (_selection(entry_id="missing"), "unknown catalog entry"),
        (
            _selection(controls=(ControlSelection("reasoning", "invented"),)),
            "unknown native-control option",
        ),
        (
            _selection(controls=(ControlSelection("invented", "low"),)),
            "control not supported",
        ),
    ],
)
def test_freeze_refuses_stale_unknown_and_arbitrary_values(
    selection: SelectionReference, reason: str
) -> None:
    with pytest.raises(TeamSelectionError, match=reason):
        freeze_team_selection(
            selection=selection,
            overrides={},
            fallbacks=(),
            required_roles=("coder",),
            records=(_record(),),
        )


@pytest.mark.parametrize(
    "expires_at",
    [None, datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)],
    ids=["no cache window", "closed cache window"],
)
def test_freeze_accepts_the_record_it_was_handed_whatever_its_cache_window(
    expires_at: datetime | None,
) -> None:
    """A selection is validated against the catalog revision it names.

    ``expires_at`` is the refresh cache's reuse window for a stored catalog, not
    a statement about this request: the records reaching freezing were just read
    through that cache, and the identity the selection is checked against is the
    revision it names - a changed catalog answers a new revision and is refused
    as stale. Refusing on the window instead gave the configured catalog TTL an
    implicit floor, and a short one made run start refuse the very selection the
    same process had served the client moments earlier.
    """
    frozen = freeze_team_selection(
        selection=_selection(),
        overrides={},
        fallbacks=(),
        required_roles=("coder",),
        records=(_record(expires_at=expires_at),),
    )

    assert frozen.selection.catalog_revision == "rev-1"
    assert frozen.selection.model_name == "gpt-exact"


def test_freeze_still_refuses_a_lane_the_service_did_not_serve_as_selectable() -> None:
    """The retained gate: the service's own selectability verdict and its status.

    A stale catalog is what a closed reuse window actually produces once the
    service re-describes the lane - the refresh failure or the staleness turns
    the served status to ``stale`` and the lane stops being selectable - so
    dropping the expiry comparison above does not admit a lane whose catalog has
    gone stale.
    """
    with pytest.raises(TeamSelectionError, match="not selectable"):
        freeze_team_selection(
            selection=_selection(),
            overrides={},
            fallbacks=(),
            required_roles=("coder",),
            records=(_record(status=CatalogStatus.STALE),),
        )


def test_freeze_refuses_unknown_roles_and_duplicate_fallbacks() -> None:
    with pytest.raises(TeamSelectionError, match="unknown role"):
        freeze_team_selection(
            selection=_selection(),
            overrides={"intruder": _selection()},
            fallbacks=(),
            required_roles=("coder",),
            records=(_record(),),
        )
    with pytest.raises(TeamSelectionError, match="duplicates"):
        freeze_team_selection(
            selection=_selection(),
            overrides={},
            fallbacks=(_selection(),),
            required_roles=("coder",),
            records=(_record(),),
        )


def test_freeze_refuses_duplicate_and_empty_required_roles() -> None:
    with pytest.raises(TeamSelectionError, match="between 1 and 64"):
        freeze_team_selection(
            selection=_selection(),
            overrides={},
            fallbacks=(),
            required_roles=(),
            records=(_record(),),
        )
    with pytest.raises(TeamSelectionError, match="duplicates"):
        freeze_team_selection(
            selection=_selection(),
            overrides={},
            fallbacks=(),
            required_roles=("coder", "coder"),
            records=(_record(),),
        )


def test_replay_normalizes_implicit_and_explicit_default_identically() -> None:
    frozen = freeze_team_selection(
        selection=_selection(),
        overrides={},
        fallbacks=(),
        required_roles=("coder",),
        records=(_record(),),
    )
    omitted, _, _ = normalize_replay_selection(
        frozen=frozen,
        selection=_selection(),
        overrides={},
        fallbacks=(),
    )
    explicit, _, _ = normalize_replay_selection(
        frozen=frozen,
        selection=_selection(controls=(ControlSelection("reasoning", "low"),)),
        overrides={},
        fallbacks=(),
    )

    assert omitted.fingerprint() == explicit.fingerprint()
    explicit_frozen = freeze_team_selection(
        selection=explicit,
        overrides={},
        fallbacks=(),
        required_roles=("coder",),
        records=(_record(),),
    )
    assert frozen.digest == explicit_frozen.digest
