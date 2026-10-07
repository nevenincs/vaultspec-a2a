"""A replay must be recognised by what the run would do.

A run id is how a caller retries after a lost acknowledgement, so the same id
arriving twice is ordinary. What is not ordinary is the same id arriving with a
different prompt or a different preset: that is a new intention wearing an old
id, and answering it with the first run's outcome would silently discard the
second.

The fingerprint draws that line. Credential values sit on the retry side of it:
they authorize a request instance rather than describe the work, and a replay
returns the original run without ever adopting the presented bundle, so a
rotated bundle is an ordinary retry. Because a stored fingerprint cannot be
recomputed - raw tokens are never persisted - each one carries the rule it was
computed under and is compared under that rule.

Built from real request objects and real credential bundles throughout, so the
field classification is exercised against the schema it describes.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from typing import Any

import pytest
from fastapi import HTTPException

from ...api.run_admission import (
    _ALWAYS_EXCLUDED,
    _PREPARE_EXCLUDED,
    CURRENT_REPLAY_DIGEST_RULE,
    ReplayDigestRule,
    replay_digest,
    replay_digest_matches,
    request_digest,
    stamped_replay_digest,
)
from ...api.schemas.gateway import ProviderCatalogSelection, RunStartRequest
from ...thread.actor_tokens import ActorTokenBundle


def _request(**overrides: Any) -> RunStartRequest:
    """Build a real request, overriding named fields through the model itself.

    ``model_copy`` rather than a keyword splat: the constructor is precisely
    typed per field, so a dictionary of mixed values cannot be splatted into it
    without a suppression, and a suppression here would hide a genuinely wrong
    field name.
    """
    base = RunStartRequest(
        team_preset="research-adr",
        message="do the thing",
        run_id="r-1",
        selection=ProviderCatalogSelection(
            schema_version=1,
            provider_id="codex",
            execution_mode="app-server",
            catalog_revision="revision-1",
            entry_id="entry-1",
            controls={"reasoning": "low"},
        ),
    )
    return base.model_copy(update=overrides) if overrides else base


def _bundle(token: str, bearer: str = "bearer-1") -> ActorTokenBundle:
    """A real engine-shaped credential bundle, never a stand-in for one."""
    return ActorTokenBundle(tokens={"coder": token}, engine_bearer=bearer)


def _current(body: RunStartRequest) -> str:
    """The plain-start replay fingerprint under the rule now in force."""
    return replay_digest(body, rule=CURRENT_REPLAY_DIGEST_RULE)


def test_identical_bodies_share_a_fingerprint() -> None:
    """An honest retry of the same work must be recognised as the same work."""
    assert _current(_request()) == _current(_request())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("message", "do something else entirely"),
        ("team_preset", "another-preset"),
        ("overrides", {"coder": _request().selection}),
        ("fallbacks", [_request().selection]),
        ("autonomous", True),
        ("title", "a different title"),
        ("feature_tag", "another-feature"),
        ("feedback_batch_id", "feedback-batch:deadbeef"),
        ("continues_run_id", "predecessor-1"),
    ],
)
def test_a_behaviour_affecting_change_produces_a_different_fingerprint(
    field: str, value: object
) -> None:
    """Anything that changes what the run does must break the match."""
    assert _current(_request()) != _current(_request(**{field: value}))


@pytest.mark.parametrize("run_id", ["r-2", "r-3"])
def test_the_run_id_is_part_of_the_digest(run_id: str) -> None:
    """The id is included, and that is harmless for the two uses it serves.

    A replay is looked up BY run id before its digest is compared, so including
    it adds nothing there; a prepare and its commit carry the same id, so it
    cannot make them differ. Asserted rather than assumed, because a future
    reader weighing whether to exclude it should see the current behaviour
    stated.
    """
    assert _current(_request()) != _current(_request(run_id=run_id))


def test_the_fingerprint_is_stable_across_processes() -> None:
    """A digest that varied per process would make every replay look changed.

    A stored fingerprint outlives the process that wrote it: the gateway that
    compares one on a retry is routinely a later process than the one that
    persisted it. So the property that matters is stability ACROSS processes, and
    two calls made side by side in this one cannot observe it - they would agree
    just as readily under a per-process salt, which is exactly the defect that
    would refuse every replay after a restart.

    This therefore computes the digest in a genuinely separate interpreter and
    compares it with the one computed here. The child is given a fresh
    ``PYTHONHASHSEED`` so the run differs from this process in the one respect
    Python varies by default.
    """
    body = _request()
    program = (
        "from vaultspec_a2a.api.run_admission import ("
        "CURRENT_REPLAY_DIGEST_RULE, replay_digest)\n"
        "from vaultspec_a2a.api.schemas.gateway import RunStartRequest\n"
        "import sys, json\n"
        "body = RunStartRequest.model_validate_json(sys.argv[1])\n"
        "print(replay_digest(body, rule=CURRENT_REPLAY_DIGEST_RULE))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program, body.model_dump_json()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "1"},
    )

    assert completed.stdout.strip() == _current(body), (
        "the replay fingerprint differs between processes, so no stored "
        "fingerprint would ever match after a gateway restart"
    )
    # Both sides are also held against a written value, so this stays a real
    # check if the subprocess ever stops being a genuinely separate process.
    assert _current(body) == _STABLE_DIGEST


# The fingerprint of ``_request()`` under the rule now in force, written down
# rather than computed. Confirmed identical across eight interpreters, including
# runs under PYTHONHASHSEED 0, 1, 12345, and 99991 - so it pins the digest that
# stored fingerprints on disk were written with. It doubles as the
# canonicalisation guard: any change to field ordering, JSON separators, the
# exclusion set, or the hash moves this value and fails here rather than
# silently refusing every replay of a run started before the change.
_STABLE_DIGEST = "74449631837868195c63ad0e9f98a4744232dfeb27a556ec04bd402c57390443"


def test_the_stored_fingerprint_value_itself_is_pinned() -> None:
    """A stored digest cannot be recomputed, so its VALUE is the contract.

    Every relational assertion in this module - two digests agree, or differ -
    is satisfied by any deterministic function of the request. None of them can
    see the algorithm change underneath. A run whose fingerprint was persisted
    before such a change replays as a different intention and is refused, and no
    test here would have gone red.
    """
    assert _current(_request()) == _STABLE_DIGEST


def test_the_current_rule_digests_exactly_what_its_specification_says() -> None:
    """Pin the current rule's bytes to an independently derived expectation.

    Every other assertion here is relational - two digests agree, or they differ.
    Relational checks are satisfied by ANY deterministic function of the request,
    so they cannot see the algorithm itself change; a digest computed over
    different bytes, or with a different hash, keeps every one of them green.

    The expectation is recomputed here from the rule as STATED - canonical JSON
    with sorted keys and fixed separators, over every field except the two
    request-identifying ones, the credential bundle, and an absent predecessor,
    hashed with SHA-256 -
    rather than by calling the production tables, so a change to those tables
    fails here instead of redefining what the rule means.
    """
    body = _request(actor_tokens=_bundle("tok-1"))

    payload = body.model_dump(
        mode="json",
        exclude={"stage", "reservation_id", "actor_tokens", "continues_run_id"},
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    assert _current(body) == expected


def test_every_excluded_field_exists_on_the_request_schema() -> None:
    """A renamed field would silently stop being excluded."""
    schema_fields = set(RunStartRequest.model_fields)
    named = _ALWAYS_EXCLUDED | _PREPARE_EXCLUDED

    missing = sorted(f for f in named if f not in schema_fields)

    assert not missing, f"exclusions name fields the schema lacks: {missing}"


def test_a_rotated_credential_bundle_replays_as_the_same_work() -> None:
    """Credential values authorize a request instance; they are not the work.

    A retry after a lost acknowledgement carries freshly minted short-lived
    tokens. The replay returns the ORIGINAL run and never adopts the presented
    bundle, so folding those values into the fingerprint would refuse exactly
    the recovery a client-supplied run id exists to serve.
    """
    minted = _request(actor_tokens=_bundle("tok-1"))
    rotated = _request(actor_tokens=_bundle("tok-2", bearer="bearer-2"))

    assert _current(minted) == _current(rotated)
    # An absent bundle is the same work as a present one, too: a retry that
    # simply stopped carrying credentials is still the same intention.
    assert _current(minted) == _current(_request())


def test_the_engine_bearer_alone_does_not_change_the_fingerprint() -> None:
    """The bearer lives INSIDE the bundle, so it must fall under one exclusion.

    Asserted independently of the per-role tokens: a future refactor that lifted
    the bearer to a top-level field would leave the bundle exclusion in place
    while quietly restoring the defect.
    """
    assert _current(_request(actor_tokens=_bundle("tok-1", bearer="b-1"))) == _current(
        _request(actor_tokens=_bundle("tok-1", bearer="b-2"))
    )


def test_every_top_level_request_field_is_consciously_classified() -> None:
    """A field ADDED to the request must be classified, not silently folded in.

    The test above catches a credential moving OUT of the bundle, because the
    helper that builds one would stop constructing. It cannot catch the opposite
    refactor - a second, top-level credential field added BESIDE the nested one -
    which would fold a credential value straight back into the fingerprint with
    every other assertion still green.

    This closes that direction from the schema side rather than by guessing at
    names: the full top-level field set is pinned, so ANY new field fails here
    and has to be answered for. A field that describes the work belongs in the
    fingerprint; one that identifies or authorizes the request instance belongs
    in an exclusion set, and adding it there means minting a new replay rule
    rather than editing an existing one. Either way the choice is made by a
    person, which is the discipline the exclusion sets themselves are named for.
    """
    assert set(RunStartRequest.model_fields) == {
        "stage",
        "reservation_id",
        "team_preset",
        "message",
        "actor_tokens",
        "metadata",
        "autonomous",
        "title",
        "feature_tag",
        "run_id",
        "selection",
        "overrides",
        "fallbacks",
        "feedback_batch_id",
        "continues_run_id",
    }


def test_a_predecessor_changes_staged_and_replay_identity() -> None:
    """An explicit lineage changes the work while an absent one keeps old bytes."""
    plain = _request()
    linked = _request(continues_run_id="predecessor-1")
    other = _request(continues_run_id="predecessor-2")

    for prepared in (True, False):
        assert request_digest(plain, prepared=prepared) != request_digest(
            linked, prepared=prepared
        )
        assert request_digest(linked, prepared=prepared) != request_digest(
            other, prepared=prepared
        )
    for rule in ReplayDigestRule:
        assert replay_digest(plain, rule=rule) != replay_digest(linked, rule=rule)
        assert replay_digest(linked, rule=rule) != replay_digest(other, rule=rule)


def test_the_commit_binding_stays_credential_sensitive() -> None:
    """The staged commit binding is deliberately stricter and is unchanged.

    Its digest is compared against the durably bound accepted request, so a
    commit retry carrying a rotated bundle is refused at the credential-binding
    boundary by design. Harmonising the two rules would erase that refusal.
    """
    minted = _request(actor_tokens=_bundle("tok-1"))
    rotated = _request(actor_tokens=_bundle("tok-2"))

    assert request_digest(minted, prepared=False) != request_digest(
        rotated, prepared=False
    )


def test_a_behaviour_affecting_change_still_conflicts_under_a_rotated_bundle() -> None:
    """Excluding credentials must not blunt the check it sits beside."""
    minted = _request(actor_tokens=_bundle("tok-1"))
    changed = _request(actor_tokens=_bundle("tok-2"), message="a second intention")

    assert _current(minted) != _current(changed)


def test_a_prepare_digest_ignores_the_prompt_and_tokens() -> None:
    """A prepare carries neither, so a commit must still bind to its prepare."""
    prepare = request_digest(_request(), prepared=True)

    assert prepare == request_digest(_request(message="different"), prepared=True)
    assert prepare != request_digest(_request(), prepared=False)


def test_a_newly_stored_fingerprint_carries_the_current_rule() -> None:
    """The stamp is what makes a stored fingerprint self-describing."""
    body = _request(actor_tokens=_bundle("tok-1"))

    stamped = stamped_replay_digest(body)

    marker, separator, digest = stamped.partition(":")
    assert separator, "a stored fingerprint must name the rule it was computed under"
    assert ReplayDigestRule(marker) is CURRENT_REPLAY_DIGEST_RULE
    assert digest == _current(body)
    # The stamp does not change what is compared: the same run retried with
    # rotated credentials still matches.
    assert replay_digest_matches(stamped, _request(actor_tokens=_bundle("tok-2")))
    assert not replay_digest_matches(stamped, _request(message="something else"))


@pytest.mark.parametrize("marker", ["r1", "r99", ""])
def test_an_unrecognised_rule_marker_is_not_comparable(marker: str) -> None:
    """A run written under a rule this process lacks must not be replayed on a guess.

    Its fingerprint was computed under a rule this process does not implement,
    so no comparison it can make is evidence of anything; reporting no match
    refuses the replay rather than answering with a run whose identity was never
    verified. ``r1`` is a retired rule and is refused like any other unknown
    marker.

    The discriminating input is a digest that DOES match the current rule: an
    implementation that quietly fell back to the current rule for an unknown
    marker would accept it, whereas a digest that disagrees with the current
    rule is refused either way and looks identical to a real refusal.
    """
    body = _request(actor_tokens=_bundle("tok-1"))

    # Control: under the marker that names it, this fingerprint really does
    # compare equal - so the refusal below is the MARKER being refused rather
    # than the digest happening to disagree.
    assert replay_digest_matches(stamped_replay_digest(body), body)

    assert not replay_digest_matches(f"{marker}:{_current(body)}", body), (
        "an unknown rule marker must refuse, not fall back to a rule it knows"
    )


def test_an_unmarked_fingerprint_is_not_comparable() -> None:
    """A bare digest names no rule, so it is refused rather than read under one."""
    body = _request(actor_tokens=_bundle("tok-1"))

    assert not replay_digest_matches(_current(body), body)


def test_persisted_digest_round_trips_through_metadata() -> None:
    """What is written must be readable, or the replay check silently disables."""
    from ...api.routes.gateway import (
        _persist_request_digest,
        _persisted_request_digest,
    )

    digest = stamped_replay_digest(_request())
    metadata = _persist_request_digest('{"feature_tag": "x"}', digest)

    assert _persisted_request_digest(metadata) == digest
    assert json.loads(metadata)["feature_tag"] == "x", "existing metadata was dropped"


def test_metadata_without_a_digest_reads_as_absent() -> None:
    """Absent must read as absent, never as an empty or matching digest."""
    from ...api.routes.gateway import _persisted_request_digest

    assert _persisted_request_digest(None) is None
    assert _persisted_request_digest("{}") is None
    assert _persisted_request_digest('{"run_lease": {"lease_id": "l"}}') is None
    assert _persisted_request_digest("not json at all") is None


def test_a_replay_of_the_recorded_request_is_accepted() -> None:
    """The check passes for the request the run was started with."""
    from ...api.routes.gateway import (
        _persist_request_digest,
        _replay_identity_or_conflict,
    )

    body = _request(actor_tokens=_bundle("tok-1"))
    metadata = _persist_request_digest(None, stamped_replay_digest(body))

    _replay_identity_or_conflict("r-1", metadata, body)
    _replay_identity_or_conflict(
        "r-1", metadata, _request(actor_tokens=_bundle("tok-2"))
    )


def test_a_replay_of_a_different_request_is_refused() -> None:
    """The same id carrying other work is a new intention, not a replay."""
    from ...api.routes.gateway import (
        _persist_request_digest,
        _replay_identity_or_conflict,
    )

    metadata = _persist_request_digest(None, stamped_replay_digest(_request()))

    with pytest.raises(HTTPException) as refused:
        _replay_identity_or_conflict(
            "r-1", metadata, _request(message="something else")
        )

    assert refused.value.status_code == 409


def test_a_replay_of_a_run_with_no_recorded_digest_is_refused() -> None:
    """A run that records no digest has no identity to compare, so it is refused."""
    from ...api.routes.gateway import _replay_identity_or_conflict

    with pytest.raises(HTTPException) as refused:
        _replay_identity_or_conflict("r-1", None, _request())

    assert refused.value.status_code == 409


def test_persisting_a_digest_preserves_the_lease_beside_it() -> None:
    """Two writers share this blob; neither may clobber the other."""
    from ...api.routes.gateway import (
        _persist_request_digest,
        _persisted_lease_id,
    )

    with_lease = '{"run_lease": {"lease_id": "lease-1", "reservation_id": "r"}}'

    merged = _persist_request_digest(with_lease, "deadbeef")

    assert _persisted_lease_id(merged) == "lease-1"
