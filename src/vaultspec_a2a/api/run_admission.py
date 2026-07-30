"""Bounded run-start request identity and per-run single-flight ordering."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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
    async def hold(self, identity: str) -> AsyncIterator[None]:
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

# Additionally excluded from a PLAIN-START REPLAY fingerprint. Credential VALUES
# authorize a request instance rather than describe the work, which is the same
# classification the always-excluded fields carry. A replay returns the ORIGINAL
# run, so a retry's presented bundle is never the bundle that run uses, and
# short-lived credentials are expected to rotate across a retry: fingerprinting
# them would refuse precisely the lost-acknowledgement recovery that a
# client-supplied run id exists to serve. The engine bearer is covered here
# because it lives inside this bundle rather than beside it.
#
# Credential COVERAGE is a different question and is enforced where it belongs:
# admission evaluates role coverage at first start and refuses an uncovering
# bundle outright. The staged COMMIT binding is deliberately stricter and keeps
# the credential-sensitive digest, so this exclusion is scoped to the replay
# rule and never widened to ``request_digest``.
_REPLAY_CREDENTIAL_EXCLUDED: frozenset[str] = frozenset({"actor_tokens"})


class ReplayDigestRule(StrEnum):
    """The field-exclusion rule a persisted replay fingerprint was computed under.

    Raw tokens are never persisted and a stored fingerprint therefore cannot be
    recomputed from the durable run. Without the rule recorded beside it, a
    byte-identical replay of a run stored under the older rule would be refused
    spuriously, so every stored fingerprint carries its rule and is compared
    under that rule rather than under the current one.

    The member VALUES appear in durable run metadata: they may be added to, but
    never renamed or reused.
    """

    #: Credential values folded into the fingerprint (pre-classification runs).
    CREDENTIAL_SENSITIVE = "r1"
    #: Credential values excluded, per the credential-value classification.
    CREDENTIAL_FREE = "r2"


#: The rule every newly persisted replay fingerprint is computed and stamped with.
CURRENT_REPLAY_DIGEST_RULE: Final = ReplayDigestRule.CREDENTIAL_FREE

# Named per rule for the same reason the exclusion sets themselves are named: a
# rule added later must state its own exclusions rather than inherit whichever
# set happens to be current.
_REPLAY_RULE_EXCLUSIONS: Final[dict[ReplayDigestRule, frozenset[str]]] = {
    ReplayDigestRule.CREDENTIAL_SENSITIVE: frozenset(),
    ReplayDigestRule.CREDENTIAL_FREE: _REPLAY_CREDENTIAL_EXCLUDED,
}

# Separates a stored fingerprint's rule marker from its hex digest. A stored
# value without it predates the marker and is read as CREDENTIAL_SENSITIVE; a
# hex digest can never contain it, so the two forms stay unambiguous.
_RULE_MARKER_SEPARATOR: Final = ":"


def _digest(body: RunStartRequest, excluded: frozenset[str]) -> str:
    """Hash one canonical request shape minus *excluded*, persisting no raw token.

    Serialisation is canonical - keys sorted, separators fixed - so the digest
    depends on the values rather than on dictionary ordering or formatting.
    """
    payload = body.model_dump(mode="json", exclude=set(excluded))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    """
    return _digest(body, _ALWAYS_EXCLUDED | _REPLAY_RULE_EXCLUSIONS[rule])


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

    *stored* is compared under ITS OWN rule, never the current one. An unstamped
    value was written before the marker existed and is read as
    :attr:`ReplayDigestRule.CREDENTIAL_SENSITIVE`, the rule it was computed
    under. An unrecognised marker - a run written by a newer process than this
    one - is not comparable at all and reports no match, so the caller refuses
    rather than answering with a run whose identity it cannot verify.

    The comparison is constant-time, matching the commit path's treatment of the
    same class of value, and compares bytes so a stored value that is somehow
    not ASCII compares unequal rather than raising.
    """
    marker, separator, hex_digest = stored.partition(_RULE_MARKER_SEPARATOR)
    if not separator:
        rule, hex_digest = ReplayDigestRule.CREDENTIAL_SENSITIVE, stored
    else:
        try:
            rule = ReplayDigestRule(marker)
        except ValueError:
            return False
    return hmac.compare_digest(
        hex_digest.encode("utf-8"),
        replay_digest(body, rule=rule).encode("utf-8"),
    )
