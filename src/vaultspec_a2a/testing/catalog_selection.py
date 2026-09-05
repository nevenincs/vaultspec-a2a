"""Build a run-start selection from a served provider catalog.

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

HTTP deliberately stays with the caller. The tiers legitimately differ - an ASGI
transport, a real socket, a sync or async client, an attach bearer - and a
transport chosen here would be wrong for most of them. Callers fetch their own
payload and pass it in, which is also what makes every function here a pure,
directly testable function of what the gateway said.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "IN_PROCESS_PROVIDER_IDS",
    "SELECTION_SCHEMA_VERSION",
    "NoSelectableLaneError",
    "in_process_selection",
    "named_lane_selection",
]

SELECTION_SCHEMA_VERSION = 1

#: The lanes that execute inside the gateway process. They need no credential,
#: bill nothing, and answer from fixed or replayed content - which is what makes
#: taking their first advertised entry harmless.
IN_PROCESS_PROVIDER_IDS = frozenset({"deterministic", "mock"})


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
    if not isinstance(payload, dict) or not isinstance(payload.get("providers"), list):
        raise NoSelectableLaneError(
            "the provider-catalog payload has no 'providers' list; got "
            f"{type(payload).__name__}"
        )
    return [record for record in payload["providers"] if isinstance(record, dict)]


def _is_selectable(record: dict[str, Any]) -> bool:
    """Whether the gateway reports this lane as usable right now.

    Both terms matter and neither implies the other: a lane can be healthy while
    advertising nothing enumerable, and a stale catalog can still list entries.
    Selecting either would be refused at run start, so they are refused here,
    where the reason is still legible.
    """
    health = record.get("health")
    catalog = record.get("catalog")
    return (
        isinstance(health, dict)
        and bool(health.get("selectable"))
        and isinstance(catalog, dict)
        and bool(catalog.get("models"))
    )


def _reference(record: dict[str, Any], entry_id: str, controls: dict[str, str]) -> dict:
    catalog = record["catalog"]
    state = catalog["state"]
    return {
        "schema_version": SELECTION_SCHEMA_VERSION,
        "provider_id": record["provider_id"],
        "execution_mode": record["execution_mode"],
        "catalog_revision": state["revision"],
        "entry_id": entry_id,
        "controls": dict(controls),
    }


def _served_summary(records: list[dict[str, Any]]) -> str:
    return (
        ", ".join(
            f"{record.get('provider_id')}/{record.get('execution_mode')}"
            f"{'' if _is_selectable(record) else ' (not selectable)'}"
            for record in records
        )
        or "nothing at all"
    )


def in_process_selection(
    payload: Any, *, prefer_provider_id: str | None = None
) -> dict[str, Any]:
    """Select an in-process lane's first advertised entry.

    ``prefer_provider_id`` names the in-process lane to use when it is served -
    typically read from a preset's own pin, because the lanes are not
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
    records = _lanes(payload)
    candidates = [
        record
        for record in records
        if record.get("provider_id") in IN_PROCESS_PROVIDER_IDS
        and _is_selectable(record)
    ]
    if not candidates:
        raise NoSelectableLaneError(
            "no selectable in-process lane is served, so this run cannot present "
            "a selection. Arm them on the gateway with "
            "VAULTSPEC_SERVE_IN_PROCESS_LANES=true (the mock lane additionally "
            "needs MOCK_API_BASE). Served: " + _served_summary(records)
        )
    record = next(
        (item for item in candidates if item["provider_id"] == prefer_provider_id),
        candidates[0],
    )
    # First advertised entry: legal here and only here. The lane bills nothing,
    # and the provider's own ordering is a better default than any ranking this
    # module could invent - which it must not, per the production resolver.
    entry_id = record["catalog"]["models"][0]["entry_id"]
    return _reference(record, entry_id, {})


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
    advertised = {
        model.get("entry_id")
        for model in record["catalog"]["models"]
        if isinstance(model, dict)
    }
    if entry_id not in advertised:
        raise NoSelectableLaneError(
            f"the lane {provider_id}/{execution_mode} does not currently advertise "
            f"entry {entry_id!r}"
        )
    return _reference(record, entry_id, controls or {})
