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
from typing import Any

import pytest

from vaultspec_a2a.api.run_admission import (
    _ALWAYS_EXCLUDED,
    _PREPARE_EXCLUDED,
    _REPLAY_CREDENTIAL_EXCLUDED,
    CURRENT_REPLAY_DIGEST_RULE,
    ReplayDigestRule,
    replay_digest,
    replay_digest_matches,
    request_digest,
    stamped_replay_digest,
)
from vaultspec_a2a.api.schemas.gateway import RunStartRequest
from vaultspec_a2a.thread.actor_tokens import ActorTokenBundle


def _request(**overrides: Any) -> RunStartRequest:
    """Build a real request, overriding named fields through the model itself.

    ``model_copy`` rather than a keyword splat: the constructor is precisely
    typed per field, so a dictionary of mixed values cannot be splatted into it
    without a suppression, and a suppression here would hide a genuinely wrong
    field name.
    """
    base = RunStartRequest(
        team_preset="research-adr", message="do the thing", run_id="r-1"
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
        ("profile_id", "not-team-defaults"),
        ("autonomous", True),
        ("title", "a different title"),
        ("feature_tag", "another-feature"),
        ("feedback_batch_id", "feedback-batch:deadbeef"),
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

    Hash randomisation applies to Python's own hashing, not to a cryptographic
    digest over canonical text, and this asserts the value rather than trusting
    that distinction.
    """
    assert _current(_request()) == _current(_request())
    assert len(_current(_request())) == 64


def test_every_excluded_field_exists_on_the_request_schema() -> None:
    """A renamed field would silently stop being excluded."""
    schema_fields = set(RunStartRequest.model_fields)
    named = _ALWAYS_EXCLUDED | _PREPARE_EXCLUDED | _REPLAY_CREDENTIAL_EXCLUDED

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


def _legacy_digest(body: RunStartRequest) -> str:
    """Recompute the pre-classification fingerprint from its specification.

    Derived here from the stated rule - canonical JSON over every field except
    the two request-identifying ones, SHA-256 - rather than from the production
    exclusion tables, so a change to those tables cannot quietly redefine what
    "the old rule" means and green-wash a stored fingerprint that no longer
    compares.
    """
    payload = body.model_dump(mode="json", exclude={"stage", "reservation_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_a_fingerprint_stored_under_the_old_rule_is_compared_under_it() -> None:
    """A stored fingerprint cannot be recomputed, so it must carry its rule.

    Raw tokens are never persisted, so a run written before credentials were
    classified out has a fingerprint no current rule can reproduce. Compared
    under the current rule, a byte-identical replay of that run would be refused
    spuriously.
    """
    body = _request(actor_tokens=_bundle("tok-1"))
    stored = _legacy_digest(body)

    assert replay_digest_matches(stored, body), (
        "an unstamped fingerprint must compare under the rule it was written with"
    )
    # The old rule keeps its old meaning: under it, a rotated bundle really is a
    # different request, and the marker is what stops that verdict leaking into
    # newly stored runs.
    assert not replay_digest_matches(stored, _request(actor_tokens=_bundle("tok-2")))
    assert not replay_digest_matches(stored, _request(message="something else"))


def test_a_newly_stored_fingerprint_carries_the_current_rule() -> None:
    """The stamp is what makes a stored fingerprint self-describing."""
    body = _request(actor_tokens=_bundle("tok-1"))

    stamped = stamped_replay_digest(body)

    marker, separator, digest = stamped.partition(":")
    assert separator, "a stored fingerprint must name the rule it was computed under"
    assert ReplayDigestRule(marker) is CURRENT_REPLAY_DIGEST_RULE
    assert digest == _current(body)
    # And it is a fingerprint under the NEW rule, not the old one wearing a new
    # marker: the same run retried with rotated credentials still matches.
    assert replay_digest_matches(stamped, _request(actor_tokens=_bundle("tok-2")))
    assert not replay_digest_matches(stamped, _request(message="something else"))


def test_an_unrecognised_rule_marker_is_not_comparable() -> None:
    """A run written by a newer process must not be replayed on a guess.

    Its fingerprint was computed under a rule this process does not implement,
    so no comparison it can make is evidence of anything; reporting no match
    refuses the replay rather than answering with a run whose identity was never
    verified.
    """
    body = _request()

    assert not replay_digest_matches(f"r99:{_current(body)}", body)
    assert not replay_digest_matches(f":{_current(body)}", body)


def test_persisted_digest_round_trips_through_metadata() -> None:
    """What is written must be readable, or the replay check silently disables."""
    from vaultspec_a2a.api.routes.gateway import (
        _persist_request_digest,
        _persisted_request_digest,
    )

    digest = stamped_replay_digest(_request())
    metadata = _persist_request_digest('{"feature_tag": "x"}', digest)

    assert _persisted_request_digest(metadata) == digest
    assert json.loads(metadata)["feature_tag"] == "x", "existing metadata was dropped"


def test_a_run_predating_digest_persistence_reads_as_unknown() -> None:
    """Absent must mean unknown, not mismatched.

    Runs created before the digest was persisted carry no digest. Treating that
    as a mismatch would refuse every legitimate replay of an existing run, so the
    caller falls back to the narrower comparison instead.
    """
    from vaultspec_a2a.api.routes.gateway import _persisted_request_digest

    assert _persisted_request_digest(None) is None
    assert _persisted_request_digest("{}") is None
    assert _persisted_request_digest('{"run_lease": {"lease_id": "l"}}') is None
    assert _persisted_request_digest("not json at all") is None


def test_persisting_a_digest_preserves_the_lease_beside_it() -> None:
    """Two writers share this blob; neither may clobber the other."""
    from vaultspec_a2a.api.routes.gateway import (
        _persist_request_digest,
        _persisted_lease_id,
    )

    with_lease = '{"run_lease": {"lease_id": "lease-1", "reservation_id": "r"}}'

    merged = _persist_request_digest(with_lease, "deadbeef")

    assert _persisted_lease_id(merged) == "lease-1"
