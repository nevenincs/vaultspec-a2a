"""Bounded run-start request identity and per-run single-flight ordering.

Run start has three replay mechanisms. Each answers a different question at a
different layer, so none can stand in for another:

- **The plain-start replay fingerprint.** Every run persists its creating
  request's :func:`stamped_replay_digest` in its durable metadata. A later
  request that meets a run already owning its id is compared against it by
  :func:`replay_digest_matches`, under the rule the fingerprint was written
  with. It asks whether that request is the same intention as the durable run.
  Credential values are excluded, so a retry carrying rotated short-lived
  tokens still recovers the original run.
- **The staged admission binding.** A prepare binds its reservation in the
  gateway's in-memory :class:`~vaultspec_a2a.control.admission.AdmissionBroker`
  to ``request_digest(prepared=True)``, beside the raw client body's digest that
  a release must present. A commit binds ``request_digest(prepared=False)``,
  which folds credential values in, and persists it with the run's lease so a
  lost commit acknowledgement replays only the exact accepted commit. It asks
  whether a commit or release belongs to that reservation, and outlives the
  reservation only as that persisted commit digest.
- **The initial-dispatch journal.** A run's first ingest is claimed under the
  ``thread-create:<run id>`` control-action idempotency key, with the accepted
  graph input as its payload, and a replayed claim is compared against the
  stored payload. It asks whether this run's first dispatch was already
  accepted with exactly that input; it keeps that dispatch exactly-once below
  the HTTP edge, and later run actions read the run's accepted program back
  from it.
"""

from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from ..thread.action_receipts import canonical_json, sha256_hex

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI

    from .schemas.gateway import RunStartRequest

__all__ = [
    "CURRENT_REPLAY_DIGEST_RULE",
    "ReplayDigestRule",
    "commit_singleflight",
    "replay_digest",
    "replay_digest_matches",
    "request_digest",
    "stamped_replay_digest",
]


@dataclass(slots=True)
class _CommitLockEntry:
    lock: asyncio.Lock
    users: int = 0


class _CommitSingleFlight:
    """Self-cleaning per-identity serialization for commit/release ordering."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._entries: dict[str, _CommitLockEntry] = {}

    @asynccontextmanager
    async def hold(self, identity: str) -> AsyncGenerator[None]:
        async with self._guard:
            entry = self._entries.get(identity)
            if entry is None:
                entry = _CommitLockEntry(lock=asyncio.Lock())
                self._entries[identity] = entry
            entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            async with self._guard:
                entry.users -= 1
                if entry.users == 0:
                    self._entries.pop(identity, None)


def commit_singleflight(app: FastAPI) -> _CommitSingleFlight:
    """Return the process-wide self-cleaning commit/release stripe map."""
    singleflight = getattr(app.state, "run_commit_singleflight", None)
    if singleflight is None:
        singleflight = _CommitSingleFlight()
        app.state.run_commit_singleflight = singleflight
    return singleflight


# Fields excluded from every request digest, with the reason each is excluded.
# Named rather than derived: a field added later must be classified by a person.
# Deriving the set would silently fold a new field in - making previously valid
# replays conflict - and defaulting new fields out would let a behaviour change
# replay as identical. Both failures are quiet.
#
# ``stage`` and ``reservation_id`` identify the request rather than describe the
# work: a prepare and its own commit differ on both while driving one run, so
# including them would make the staged path conflict with itself.
_ALWAYS_EXCLUDED: frozenset[str] = frozenset({"stage", "reservation_id"})

# Additionally excluded when digesting a PREPARE, which carries no opening
# prompt and no tokens yet. Comparing them would make every commit differ from
# the prepare it binds to.
_PREPARE_EXCLUDED: frozenset[str] = frozenset({"message", "actor_tokens"})


class ReplayDigestRule(StrEnum):
    """The field-exclusion rule a persisted replay fingerprint was computed under.

    Raw tokens are never persisted and a stored fingerprint therefore cannot be
    recomputed from the durable run. Without the rule recorded beside it, a
    byte-identical replay of a run stored under an older rule would be refused
    spuriously, so every stored fingerprint carries its rule and is compared
    under that rule rather than under the current one.

    The member VALUES appear in durable run metadata: they may be added to, but
    never renamed or reused. ``"r1"`` named a retired rule that folded credential
    values into the fingerprint; it stays reserved so no later rule can be
    mistaken for it.
    """

    #: Credential values excluded, per the credential-value classification.
    CREDENTIAL_FREE = "r2"


#: The rule every newly persisted replay fingerprint is computed and stamped with.
CURRENT_REPLAY_DIGEST_RULE: Final = ReplayDigestRule.CREDENTIAL_FREE

# Each rule states its COMPLETE exclusion set as a frozen literal rather than
# composing one from the sets that happen to be current. A rule describes bytes
# already on disk, so it is immutable: composing it would let a later addition
# to the shared set silently redefine an older rule and refuse byte-identical
# replays of runs stored under it - and those digests cannot be recomputed,
# because raw tokens are deliberately never persisted. Changing what is excluded
# therefore means MINTING A NEW RULE and moving the current pointer to it, never
# editing an existing entry. The duplication with the staged sets above is the
# price of that immutability and is deliberate.
_REPLAY_RULE_EXCLUSIONS: Final[dict[ReplayDigestRule, frozenset[str]]] = {
    ReplayDigestRule.CREDENTIAL_FREE: frozenset(
        {"stage", "reservation_id", "actor_tokens"}
    ),
}

# Separates a stored fingerprint's rule marker from its hex digest. A hex digest
# can never contain it, so the split is unambiguous.
_RULE_MARKER_SEPARATOR: Final = ":"


def _digest(body: RunStartRequest, excluded: frozenset[str]) -> str:
    """Hash one canonical request shape minus *excluded*, persisting no raw token.

    Serialisation is canonical - keys sorted, separators fixed - so the digest
    depends on the values rather than on dictionary ordering or formatting.
    """
    omitted = set(excluded)
    # Dropped under every rule rather than listed in one rule's exclusion set:
    # an unset continuation id keeps the payload of a request that never named
    # one byte-identical to the fingerprint stored before the field existed.
    if body.continues_run_id is None:
        omitted.add("continues_run_id")
    payload = body.model_dump(mode="json", exclude=omitted)
    return sha256_hex(canonical_json(payload).encode("utf-8"))


def request_digest(body: RunStartRequest, *, prepared: bool) -> str:
    """Hash the STAGED admission binding of a request - prepare, then commit.

    Two requests that would produce the same run share a digest; any difference
    in what the run would do produces a different one. ``prepared=True`` binds a
    reservation across prepare/release, and ``prepared=False`` binds the commit
    that consumes it.

    The commit binding is deliberately the stricter of the two rules and folds
    credential values in. It is compared against the durably bound accepted
    request under per-run single-flight, so a commit retry carrying a rotated
    bundle is REFUSED at the credential-binding boundary by design. The
    plain-start replay path answers a different question and uses
    :func:`replay_digest`; the two rules are deliberately not harmonised.
    """
    excluded = _ALWAYS_EXCLUDED | _PREPARE_EXCLUDED if prepared else _ALWAYS_EXCLUDED
    return _digest(body, excluded)


def replay_digest(body: RunStartRequest, *, rule: ReplayDigestRule) -> str:
    """Hash a PLAIN-START replay fingerprint under *rule*.

    This is what lets a replayed run id be answered with the original outcome
    when the request matches, and refused when it does not - a replay carrying a
    different prompt or preset is a new intention wearing an old id. *rule* is
    explicit rather than defaulted so a comparison against a stored fingerprint
    cannot silently drift onto the current rule.

    The rule's exclusion set is used WHOLE rather than combined with the staged
    sets, so an older rule keeps describing exactly the bytes it was computed
    over however the current classification later changes.
    """
    return _digest(body, _REPLAY_RULE_EXCLUSIONS[rule])


def stamped_replay_digest(body: RunStartRequest) -> str:
    """Return *body*'s replay fingerprint stamped with the rule it was computed under.

    The stamped form is what is persisted: it keeps a stored fingerprint
    self-describing, so a run started under an older rule stays comparable after
    the rule changes.
    """
    digest = replay_digest(body, rule=CURRENT_REPLAY_DIGEST_RULE)
    return f"{CURRENT_REPLAY_DIGEST_RULE.value}{_RULE_MARKER_SEPARATOR}{digest}"


def replay_digest_matches(stored: str, body: RunStartRequest) -> bool:
    """Report whether *body* replays the request *stored* fingerprints.

    *stored* is compared under ITS OWN rule, never the current one. A value with
    no recognised marker - an unmarked value, or a run written by a newer
    process than this one - is not comparable at all and reports no match, so
    the caller refuses rather than answering with a run whose identity it
    cannot verify.

    The DIGEST comparison is constant-time, matching the commit path's treatment
    of the same class of value, and compares bytes so a stored value that is
    somehow not ASCII compares unequal rather than raising. The rule marker
    ahead of it is not: parsing it, and refusing an unrecognised one, both
    return before the digests are ever compared. That is deliberate and not a
    leak - the marker is a public, non-secret label naming which rule computed
    the stored value, and it carries no material an attacker could learn by
    timing. Stating it that way keeps the guarantee checkable against the code
    rather than one notch stronger than it.
    """
    marker, separator, hex_digest = stored.partition(_RULE_MARKER_SEPARATOR)
    if not separator:
        return False
    try:
        rule = ReplayDigestRule(marker)
    except ValueError:
        return False
    return hmac.compare_digest(
        hex_digest.encode("utf-8"),
        replay_digest(body, rule=rule).encode("utf-8"),
    )
