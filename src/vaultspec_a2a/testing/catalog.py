"""Select a lane from a served provider catalog, for every test tier.

Run start refuses a body without a ``selection`` and revalidates the reference it
receives against the catalog served FOR THAT WORKSPACE, so a hand-written
reference is refused even when its shape is perfect: it has to name a lane the
gateway actually reports selectable, at that lane's current revision. Every test
tier needs that derivation, and each had grown its own copy.

**This module owns the MECHANISM, not the policy.** Reading a catalog payload,
finding a lane, checking it is still selectable and current, checking the entry
is really advertised, and rendering the wire shape are the same everywhere. WHICH
lane and WHICH entry is a decision only the caller can make, and flattening that
would hand a test a lane its author never chose.

The policy is therefore expressed by WHICH FUNCTION you call, not by a flag:

- :func:`in_process_selection` searches only the in-process lanes and takes the
  first entry a lane advertises.
- :func:`named_lane_selection` requires the caller to name the lane AND the
  entry, and validates both against what is currently served.
- :func:`selection_from_served_catalog` and
  :func:`override_selection_from_served_catalog` take the lane an operator
  declared in the environment and hold it to the full selectable, authenticated
  and admitted standard before a billable turn may use it.

That split is the point. The production resolver
(``cli/main.py::_resolve_catalog_selection``) states the rule this must obey - it
"deliberately never ranks entries, reads a display name as a quality or price
signal, or falls back to 'the first one'" - because choosing on the caller's
behalf is how a tool quietly decides what a provider charges for. Taking the
first advertised entry is exactly that fallback, and it is tolerable ONLY on the
in-process lanes, where nothing is billed and no operator exists to ask.

So the dangerous combination - an external, billable lane with an entry nobody
chose - is not discouraged here, it is unrepresentable: no function in this
module accepts an external lane without also requiring its entry id. That matters
because the failure it prevents is silent. "Take the first selectable lane"
resolves, on any developer machine holding a live provider session, to a real
paid lane - and a certification suite whose whole point is in-process replay
would have been billing a provider while still reporting green.

The wire shape is :class:`~vaultspec_a2a.api.schemas.gateway.ProviderCatalogSelection`
and the in-process lane identities are
:data:`~vaultspec_a2a.providers.in_process_catalog.IN_PROCESS_EXECUTION_MODES`;
both are read from production rather than restated here, so neither can drift.

HTTP stays with the caller's CLIENT. The tiers legitimately differ - an ASGI
transport, a real socket, a sync or async client, an attach bearer - and a
transport chosen here would be wrong for most of them. The fetch helpers take the
client the caller already holds; only the by-URL variant opens its own.

Production imports are deferred into the functions that need them: the root
conftest and the ``dev`` tooling import this module before a test environment is
declared, and the settings singleton must not be reached by that import.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

import httpx

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..api.schemas.gateway import ProviderCatalogSelection
    from ..graph.enums import Provider
    from ..providers.provider_catalog import ProviderRecord, SelectionReference

__all__ = [
    "LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON",
    "LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON",
    "LIVE_PROVIDER_PREREQUISITES",
    "NoSelectableLaneError",
    "async_catalog_run_fields",
    "async_fetch_in_process_selection",
    "async_fetch_provider_catalog",
    "catalog_run_fields",
    "declared_lane_model_value",
    "fetch_in_process_selection",
    "fetch_in_process_selection_at",
    "fetch_provider_catalog",
    "in_process_lane_selection",
    "in_process_selection",
    "live_provider_catalog_selector_is_configured",
    "live_provider_override_selector_is_configured",
    "named_lane_selection",
    "override_selection_from_served_catalog",
    "selection_from_served_catalog",
]

_CATALOG_PATH: Final = "/v1/provider-catalog"

# The first catalog read for a workspace probes every registered lane over real
# subprocesses and sockets, so it legitimately outlasts the short budgets callers
# build their clients with to assert that a gateway answers its verbs promptly.
# The budget is applied PER REQUEST rather than by building a second client: a
# second client keeps only the caller's base_url and silently drops its
# transport, which sends an in-process ASGI caller's unroutable base_url to real
# DNS.
_CATALOG_READ_TIMEOUT_S: Final = 240.0

type _SelectionKey = tuple[str, str, str | None]

# One selection per gateway, workspace and lane preference. A replayed or
# committed request is only recognised when its selection is byte-identical to
# the one it replays, so the choice is made once and handed out as fresh copies.
_SELECTION_CACHE: dict[_SelectionKey, ProviderCatalogSelection] = {}


class NoSelectableLaneError(RuntimeError):
    """The served catalog offers no lane matching what the caller asked for.

    Raised rather than returned as ``None`` so a caller cannot accidentally send
    a run with no selection and read the resulting 422 as a routing fault. The
    message names what was searched for and what was actually served, because the
    usual cause is an environment fact - an unarmed lane, an absent credential -
    that is invisible from the failure alone.
    """


def _lanes(payload: Any) -> list[dict[str, Any]]:
    """Return the served provider records, or fail naming what arrived instead."""
    if not isinstance(payload, dict):
        raise NoSelectableLaneError(
            "the provider-catalog payload has no 'providers' list; got "
            f"{type(payload).__name__}"
        )
    payload = cast("dict[str, Any]", payload)
    raw_providers = payload.get("providers")
    if not isinstance(raw_providers, list):
        raise NoSelectableLaneError(
            "the provider-catalog payload has no 'providers' list; got "
            f"{type(payload).__name__}"
        )
    providers = cast("list[Any]", raw_providers)
    return [record for record in providers if isinstance(record, dict)]


def _is_selectable(record: dict[str, Any]) -> bool:
    """Whether the gateway reports this lane as usable right now.

    Both terms matter and neither implies the other: a lane can be healthy while
    advertising nothing enumerable, and a stale catalog can still list entries.
    Selecting either would be refused at run start, so they are refused here,
    where the reason is still legible.
    """
    health = record.get("health")
    catalog = record.get("catalog")
    if not isinstance(health, dict) or not isinstance(catalog, dict):
        return False
    health = cast("dict[str, Any]", health)
    catalog = cast("dict[str, Any]", catalog)
    return bool(health.get("selectable")) and bool(catalog.get("models"))


def _is_in_process(record: dict[str, Any]) -> bool:
    """Whether the record is one of the lanes that execute inside the gateway."""
    from ..providers.in_process_catalog import IN_PROCESS_EXECUTION_MODES

    return any(
        provider.value == record.get("provider_id")
        and execution_mode == record.get("execution_mode")
        for provider, execution_mode in IN_PROCESS_EXECUTION_MODES.items()
    )


def _selection(
    record: dict[str, Any], entry_id: str, controls: Mapping[str, str]
) -> ProviderCatalogSelection:
    """Build the wire reference for one served lane record, through its schema."""
    from ..api.schemas.gateway import ProviderCatalogSelection
    from ..providers.provider_catalog import SELECTION_SCHEMA_VERSION

    revision = (record["catalog"].get("state") or {}).get("revision")
    if not revision:
        raise NoSelectableLaneError(
            f"the lane {record.get('provider_id')}/{record.get('execution_mode')} "
            "served no catalog revision to select against"
        )
    return ProviderCatalogSelection(
        schema_version=SELECTION_SCHEMA_VERSION,
        provider_id=record["provider_id"],
        execution_mode=record["execution_mode"],
        catalog_revision=revision,
        entry_id=entry_id,
        controls=dict(controls),
    )


def _served_summary(records: list[dict[str, Any]]) -> str:
    return (
        ", ".join(
            f"{record.get('provider_id')}/{record.get('execution_mode')}"
            f"{'' if _is_selectable(record) else ' (not selectable)'}"
            for record in records
        )
        or "nothing at all"
    )


def _choose_in_process(
    payload: Any, prefer_provider_id: str | None
) -> ProviderCatalogSelection:
    records = _lanes(payload)
    candidates = [
        record
        for record in records
        if _is_in_process(record) and _is_selectable(record)
    ]
    if not candidates:
        raise NoSelectableLaneError(
            "no selectable in-process lane is served, so this run cannot present "
            "a selection. Arm them on the gateway with "
            "VAULTSPEC_A2A_SERVE_IN_PROCESS_LANES=true (the mock lane additionally "
            "needs VAULTSPEC_A2A_MOCK_API_BASE). Served: " + _served_summary(records)
        )
    record = next(
        (item for item in candidates if item["provider_id"] == prefer_provider_id),
        candidates[0],
    )
    # First advertised entry: legal here and only here. The lane bills nothing,
    # and the provider's own ordering is a better default than any ranking this
    # module could invent - which it must not, per the production resolver.
    return _selection(record, record["catalog"]["models"][0]["entry_id"], {})


def _named_selection(
    payload: Any,
    *,
    provider_id: str,
    execution_mode: str,
    entry_id: str,
    controls: Mapping[str, str] | None,
) -> ProviderCatalogSelection:
    records = _lanes(payload)
    matching = [
        record
        for record in records
        if record.get("provider_id") == provider_id
        and record.get("execution_mode") == execution_mode
    ]
    if len(matching) != 1:
        raise NoSelectableLaneError(
            f"the lane {provider_id}/{execution_mode} is not uniquely served "
            f"({len(matching)} matches). Served: " + _served_summary(records)
        )
    record = matching[0]
    if not _is_selectable(record):
        raise NoSelectableLaneError(
            f"the lane {provider_id}/{execution_mode} is served but not currently "
            "selectable, or advertises no models"
        )
    advertised: set[Any] = {
        cast("dict[str, Any]", model).get("entry_id")
        for model in record["catalog"]["models"]
        if isinstance(model, dict)
    }
    if entry_id not in advertised:
        raise NoSelectableLaneError(
            f"the lane {provider_id}/{execution_mode} does not currently advertise "
            f"entry {entry_id!r}"
        )
    return _selection(record, entry_id, controls or {})


def in_process_selection(
    payload: Any, *, prefer_provider_id: str | None = None
) -> dict[str, Any]:
    """Select an in-process lane's first advertised entry.

    ``prefer_provider_id`` names the in-process lane to use when it is served.
    Callers pass the lane their preset is pinned to, because the lanes are not
    interchangeable: the mock lane replays a tape and the deterministic lane
    answers from fixed role-keyed content, so a preset answered by the wrong one
    still completes while testing something else entirely. An unserved or unnamed
    preference falls back to the first in-process lane rather than failing, since
    any of them satisfies a caller that expressed no preference.

    An EXTERNAL lane is never returned, even when one is selectable and the
    in-process lanes are not. That is the whole safety property: the caller asked
    for a lane that bills nothing, and silently upgrading it to a real provider
    would be the expensive surprise this module exists to prevent.
    """
    return _choose_in_process(payload, prefer_provider_id).model_dump(mode="json")


def named_lane_selection(
    payload: Any,
    *,
    provider_id: str,
    execution_mode: str,
    entry_id: str,
    controls: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Select an explicitly named lane and entry, validated against the catalog.

    The only way to reach an external lane. Every identifier is the caller's, and
    each is checked against what is served right now rather than trusted: a lane
    that has stopped being selectable, or an entry the lane no longer advertises,
    fails here with a legible reason instead of as a 422 from run start.

    The revision comes from THIS payload, never from the caller, so a selection
    assembled from a stale reading is refused rather than replayed against an
    expired catalog revision.
    """
    return _named_selection(
        payload,
        provider_id=provider_id,
        execution_mode=execution_mode,
        entry_id=entry_id,
        controls=controls,
    ).model_dump(mode="json")


def fetch_provider_catalog(
    client: httpx.Client,
    workspace_root: str,
    *,
    timeout: float = _CATALOG_READ_TIMEOUT_S,
) -> Any:
    """Read the catalog the gateway serves for *workspace_root*."""
    return _catalog_body(
        client.get(
            _CATALOG_PATH, params={"workspace_root": workspace_root}, timeout=timeout
        )
    )


async def async_fetch_provider_catalog(
    client: httpx.AsyncClient,
    workspace_root: str,
    *,
    timeout: float = _CATALOG_READ_TIMEOUT_S,
) -> Any:
    """The async twin of :func:`fetch_provider_catalog`."""
    return _catalog_body(
        await client.get(
            _CATALOG_PATH, params={"workspace_root": workspace_root}, timeout=timeout
        )
    )


def _catalog_body(response: httpx.Response) -> Any:
    assert response.status_code == 200, (
        f"the gateway could not serve its provider catalog: "
        f"{response.status_code} {response.text}"
    )
    return response.json()


def _selection_key(
    client: httpx.Client | httpx.AsyncClient,
    workspace_root: str,
    prefer_provider_id: str | None,
) -> _SelectionKey:
    return (str(client.base_url), workspace_root, prefer_provider_id)


def fetch_in_process_selection(
    client: httpx.Client,
    workspace_root: str,
    *,
    prefer_provider_id: str | None = None,
    cache: bool = False,
    timeout: float = _CATALOG_READ_TIMEOUT_S,
) -> dict[str, Any]:
    """Read the served catalog and select an in-process lane from it.

    ``cache`` remembers the choice per gateway, workspace and preference, for a
    caller that sends the same selection on several requests; the default reads
    afresh, which is what a test that restarts its gateway needs.
    """
    key = _selection_key(client, workspace_root, prefer_provider_id)
    chosen = _SELECTION_CACHE.get(key) if cache else None
    if chosen is None:
        chosen = _choose_in_process(
            fetch_provider_catalog(client, workspace_root, timeout=timeout),
            prefer_provider_id,
        )
        if cache:
            _SELECTION_CACHE[key] = chosen
    return chosen.model_dump(mode="json")


async def async_fetch_in_process_selection(
    client: httpx.AsyncClient,
    workspace_root: str,
    *,
    prefer_provider_id: str | None = None,
    cache: bool = False,
    timeout: float = _CATALOG_READ_TIMEOUT_S,
) -> dict[str, Any]:
    """The async twin of :func:`fetch_in_process_selection`.

    Deliberately a twin rather than a shared core: the sync and async clients do
    not share a request method, and threading a maybe-awaitable through one
    function reads worse than two short ones that each do the obvious thing. Both
    share one cache, so whichever runs first pays for the read.
    """
    key = _selection_key(client, workspace_root, prefer_provider_id)
    chosen = _SELECTION_CACHE.get(key) if cache else None
    if chosen is None:
        chosen = _choose_in_process(
            await async_fetch_provider_catalog(client, workspace_root, timeout=timeout),
            prefer_provider_id,
        )
        if cache:
            _SELECTION_CACHE[key] = chosen
    return chosen.model_dump(mode="json")


def fetch_in_process_selection_at(
    base_url: str,
    workspace_root: str,
    *,
    headers: Mapping[str, str] | None = None,
    prefer_provider_id: str | None = None,
    cache: bool = False,
    timeout: float = _CATALOG_READ_TIMEOUT_S,
) -> dict[str, Any]:
    """:func:`fetch_in_process_selection` for a caller that holds only a URL."""
    with httpx.Client(base_url=base_url, headers=headers) as client:
        return fetch_in_process_selection(
            client,
            workspace_root,
            prefer_provider_id=prefer_provider_id,
            cache=cache,
            timeout=timeout,
        )


def catalog_run_fields(
    client: httpx.Client, *, workspace_root: str | None = None
) -> dict[str, Any]:
    """Return the run-start fields an explicit catalog selection now requires.

    The reference is read from the live served catalog the way a real client must,
    through the shared selection mechanism, which returns an IN-PROCESS lane and
    refuses to return any other. The gateway suites assert on gateway plumbing, so
    the lane that answers must be the one that bills nothing.

    A canned literal would be the tempting shortcut and would be wrong twice
    over: it would break whenever the catalog's revision moved, and it would let
    a test assert against a lane the gateway would never serve. Reading keeps
    the fixture honest about what the gateway is offering at that moment.

    ``workspace_root`` is returned alongside because the same gate refuses a
    selection with no existing workspace to anchor it in.
    """
    root = workspace_root or str(Path.cwd())
    return {
        "selection": fetch_in_process_selection(client, root, cache=True),
        "metadata": {"workspace_root": root},
    }


async def async_catalog_run_fields(
    client: httpx.AsyncClient, *, workspace_root: str | None = None
) -> dict[str, Any]:
    """The async twin of :func:`catalog_run_fields`, for httpx.AsyncClient callers."""
    root = workspace_root or str(Path.cwd())
    return {
        "selection": await async_fetch_in_process_selection(client, root, cache=True),
        "metadata": {"workspace_root": root},
    }


def in_process_lane_selection(
    provider: Provider,
) -> tuple[ProviderRecord, SelectionReference]:
    """Build an in-process lane's served record offline, and name its first entry.

    The record is what the gateway would serve for the lane, assembled without a
    gateway for a test that freezes a selection directly, with the expiry the
    service would have stamped on it. The reference takes the lane's first entry
    under the same rule as :func:`in_process_selection`: legal on a lane that
    bills nothing, and only there.
    """
    from datetime import UTC, datetime

    from ..providers.in_process_catalog import (
        discover_in_process_catalog,
        in_process_catalog_key,
    )
    from ..providers.provider_catalog import (
        AdmissionState,
        AuthenticationState,
        CatalogStatus,
        HealthState,
        ProviderHealthAxes,
        ProviderRecord,
        SelectionReference,
        StructuredProviderHealth,
    )
    from ..providers.provider_catalog_service import stamp_catalog_expiry

    key = in_process_catalog_key(provider)
    record = ProviderRecord(
        provider_id=key.provider_id,
        display_name=f"{provider.value.capitalize()} (in-process)",
        execution_mode=key.execution_mode,
        health=StructuredProviderHealth.derive(
            axes=ProviderHealthAxes(
                configured=HealthState.AVAILABLE,
                transport=HealthState.AVAILABLE,
                authentication=AuthenticationState.NOT_APPLICABLE,
                catalog=CatalogStatus.AVAILABLE,
                admission=AdmissionState.ADMITTED,
            ),
            checked_at=datetime.now(UTC),
        ),
        catalog=stamp_catalog_expiry(discover_in_process_catalog(key).catalog),
    )
    reference = SelectionReference(
        provider_id=key.provider_id,
        execution_mode=key.execution_mode,
        catalog_revision=record.catalog.state.revision or "",
        entry_id=record.catalog.models[0].entry_id,
    )
    return record, reference


LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON: Final[tuple[str, ...]] = (
    "VAULTSPEC_A2A_LIVE_PROVIDER_ID",
    "VAULTSPEC_A2A_LIVE_EXECUTION_MODE",
    "VAULTSPEC_A2A_LIVE_ENTRY_ID",
    "VAULTSPEC_A2A_LIVE_CONTROL_ID",
    "VAULTSPEC_A2A_LIVE_OPTION_ID",
)

#: A SECOND operator-supplied lane, for a proof that needs two lanes in one run.
#:
#: A mixed-provider certification routes most roles to one lane and one role to
#: another, and the whole point of it is that the two differ. That cannot be
#: expressed by the single selector above, and it must not be faked by picking a
#: second lane here - this module ranks nothing. So the second lane is declared
#: exactly like the first, and a mixed proof that has not been given one SKIPS.
#: Degrading it to a single-lane run instead would keep the label "mixed" on a
#: run that no longer proves anything mixed, which is worse than not running.
LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON: Final[tuple[str, ...]] = (
    "VAULTSPEC_A2A_LIVE_OVERRIDE_PROVIDER_ID",
    "VAULTSPEC_A2A_LIVE_OVERRIDE_EXECUTION_MODE",
    "VAULTSPEC_A2A_LIVE_OVERRIDE_ENTRY_ID",
    "VAULTSPEC_A2A_LIVE_OVERRIDE_CONTROL_ID",
    "VAULTSPEC_A2A_LIVE_OVERRIDE_OPTION_ID",
)

LIVE_PROVIDER_PREREQUISITES: Final[tuple[str, ...]] = (
    "dashboard-engine",
    "provider-catalog-live-selection",
)


@dataclass(frozen=True, slots=True)
class LiveProviderCatalogSelector:
    """Opaque, operator-supplied identifiers for one billable proof turn."""

    provider_id: str
    execution_mode: str
    entry_id: str
    control_id: str
    option_id: str


def live_provider_catalog_selector_is_configured() -> bool:
    """Return whether every required explicit proof selector is non-blank."""
    return all(
        (os.environ.get(name) or "").strip()
        for name in LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON
    )


def live_provider_override_selector_is_configured() -> bool:
    """Return whether a complete SECOND lane has been declared for mixed proofs."""
    return all(
        (os.environ.get(name) or "").strip()
        for name in LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON
    )


def _selector_from(names: tuple[str, ...], *, what: str) -> LiveProviderCatalogSelector:
    """Read one declared lane's identifiers from its own environment names."""
    values = {name: (os.environ.get(name) or "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    assert not missing, (
        f"the {what} live selection is incomplete: missing {', '.join(missing)}"
    )
    provider, mode, entry, control, option = names
    return LiveProviderCatalogSelector(
        provider_id=values[provider],
        execution_mode=values[mode],
        entry_id=values[entry],
        control_id=values[control],
        option_id=values[option],
    )


def override_selection_from_served_catalog(
    payload: object,
) -> ProviderCatalogSelection:
    """Validate the SECOND declared lane, for a per-role override.

    Held to exactly the same current-selectable-authenticated-admitted standard
    as the primary: an override is a lane a run really executes a role on, so a
    weaker check here would admit through the side door precisely what the front
    door refuses.
    """
    return _declared_selection(
        _selector_from(LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON, what="override"),
        payload,
        what="override",
    )


def selection_from_served_catalog(payload: object) -> ProviderCatalogSelection:
    """Validate the operator selection against the current public catalog.

    The returned selection is deliberately assembled only from A2A-issued
    values.  Its revision comes from this response, rather than environment
    configuration, so an old operator selection is rejected instead of being
    replayed against an expired catalog revision.
    """
    return _declared_selection(
        _selector_from(
            LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON, what="provider-catalog"
        ),
        payload,
        what="explicitly configured",
    )


def _declared_selection(
    selector: LiveProviderCatalogSelector, payload: object, *, what: str
) -> ProviderCatalogSelection:
    """Prove one declared lane is still served, selectable, and admitted.

    The named-lane check owns whether the lane is uniquely served, selectable,
    serves a revision and still advertises the entry. What this adds is the
    standard only a billable turn needs: current authentication, completed-turn
    admission, an unexpired catalog, and a native control the entry really carries.
    """
    from datetime import UTC, datetime

    from ..api.schemas.provider_catalog import ProviderCatalogResponse
    from ..providers.provider_catalog import (
        AdmissionState,
        AuthenticationState,
        CatalogStatus,
        HealthState,
    )

    selection = _named_selection(
        payload,
        provider_id=selector.provider_id,
        execution_mode=selector.execution_mode,
        entry_id=selector.entry_id,
        controls={selector.control_id: selector.option_id},
    )
    catalog = ProviderCatalogResponse.model_validate(payload)
    lane = next(
        record
        for record in catalog.providers
        if record.provider_id == selector.provider_id
        and record.execution_mode == selector.execution_mode
    )
    health = lane.health
    assert health.configured is HealthState.AVAILABLE, (
        f"the {what} provider/lane is no longer configured"
    )
    assert health.transport is HealthState.AVAILABLE, (
        f"the {what} provider/lane has no current transport evidence"
    )
    assert health.authentication is AuthenticationState.AUTHENTICATED, (
        f"the {what} provider/lane is not currently authenticated"
    )
    assert health.catalog is CatalogStatus.AVAILABLE, (
        f"the {what} provider/lane catalog is not available"
    )
    assert health.admission is AdmissionState.ADMITTED, (
        f"the {what} provider/lane has no completed-turn admission evidence"
    )

    state = lane.catalog.state
    assert state.status is CatalogStatus.AVAILABLE, (
        f"the {what} provider/lane has no available catalog state"
    )
    assert state.expires_at is not None and state.expires_at > datetime.now(UTC), (
        f"the {what} provider/lane catalog is stale"
    )

    entry = next(
        entry for entry in lane.catalog.models if entry.entry_id == selector.entry_id
    )
    assert selector.control_id in entry.native_control_ids, (
        f"the {what} native control is not attached to the served entry"
    )
    controls = [
        control
        for control in lane.catalog.native_controls
        if control.control_id == selector.control_id
    ]
    assert len(controls) == 1, (
        f"the {what} native control is not currently served by its lane"
    )
    assert any(
        option.option_id == selector.option_id for option in controls[0].options
    ), f"the {what} native-control option is not currently served"
    return selection


async def declared_lane_model_value(
    provider_id: str, workspace_root: Path
) -> tuple[str | None, str]:
    """Resolve the operator-declared entry to the model value that lane serves.

    Returns ``(value, reason)``. ``value`` is ``None`` when the declaration
    cannot be honoured and ``reason`` says exactly why, so the CALLER decides
    whether that is a skip or a failure - which is the prerequisite rule's job,
    not this module's.

    This exists so a billable direct-factory test can name a model without
    choosing one. Taking "the first served entry" is the fallback this module is
    built to make unrepresentable: on any developer machine holding a live
    provider session it resolves to a real paid lane that nobody selected. The
    operator names the entry; live discovery supplies its current value, so a
    declaration that has gone stale fails legibly instead of spending on a model
    the declaration no longer identifies.
    """
    from ..providers.factory import ProviderFactory

    declared = (os.environ.get("VAULTSPEC_A2A_LIVE_PROVIDER_ID") or "").strip()
    if declared != provider_id:
        return None, (
            f"the declared lane is {declared!r}, not {provider_id!r}"
            if declared
            else "no lane is declared"
        )
    entry_id = (os.environ.get("VAULTSPEC_A2A_LIVE_ENTRY_ID") or "").strip()
    if not entry_id:
        return None, "the declaration names no entry id"

    registration = next(
        (
            item
            for item in ProviderFactory().catalog_registrations(workspace_root)
            if item.key.provider_id == provider_id
        ),
        None,
    )
    if registration is None:
        return None, f"no catalog lane is registered for {provider_id!r}"

    discovery = await registration.discover()
    served = {
        model.entry_id: model.provider_value for model in discovery.catalog.models
    }
    if entry_id not in served:
        return None, (
            f"the declared entry {entry_id!r} is no longer served; {provider_id} "
            f"now advertises {sorted(served.values())}"
        )
    return served[entry_id], ""
