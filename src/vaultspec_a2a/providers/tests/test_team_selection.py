"""Real domain-contract tests for explicit team selection admission."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

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


def _record() -> ProviderRecord:
    key = ProviderCatalogKey(provider_id="codex", execution_mode="app-server")
    catalog = ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=datetime(2026, 1, 1, tzinfo=UTC),
            revision="rev-1",
            expires_at=_CHECKED,
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
        configured=HealthState.AVAILABLE,
        transport=HealthState.AVAILABLE,
        authentication=AuthenticationState.AUTHENTICATED,
        catalog=CatalogStatus.AVAILABLE,
        admission=AdmissionState.ADMITTED,
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return ProviderRecord(
        provider_id="codex",
        display_name="Codex",
        execution_mode="app-server",
        health=health,
        catalog=catalog,
    )


def _selection(**changes: object) -> SelectionReference:
    values = {
        "schema_version": 1,
        "provider_id": "codex",
        "execution_mode": "app-server",
        "catalog_revision": "rev-1",
        "entry_id": "entry-1",
        "controls": (),
    }
    values.update(changes)
    return SelectionReference(**values)  # type: ignore[arg-type]


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
    assert frozen.compiler_map()["coder"]["model_name"] == "gpt-exact"
    assert frozen.to_record()["selection"]["controls"] == {"reasoning": "low"}


@pytest.mark.parametrize(
    ("selection", "reason"),
    [
        (_selection(catalog_revision="old"), "stale catalog revision"),
        (_selection(entry_id="missing"), "unknown catalog entry"),
        (
            _selection(
                controls=(ControlSelection("reasoning", "invented"),)
            ),
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
        record=frozen.to_record(),
        selection=_selection(),
        overrides={},
        fallbacks=(),
    )
    explicit, _, _ = normalize_replay_selection(
        record=frozen.to_record(),
        selection=_selection(
            controls=(ControlSelection("reasoning", "low"),)
        ),
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
