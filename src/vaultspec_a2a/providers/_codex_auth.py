"""Seed a per-run Codex login, and return a refreshed one to where it came from.

Codex authenticates from a file in its home. A run gets its own home (see
``_codex_config_home``) so it cannot inherit the operator's ambient MCP
configuration, and the login is copied in to keep the run authenticated. That
copy is the problem this module exists for: Codex ROTATES the refresh token
mid-run and writes the new one into the home it is using, so a run home that is
simply deleted afterwards takes the live credential with it and leaves the
operator's own copy holding a token the provider has already retired. The next
login attempt is then refused for reusing a spent token - a logged-out operator
as the observable symptom of a cleanup.

So the copy is tracked: what was seeded is recorded beside it, and at cleanup a
changed credential is written back to the home it came from, atomically and under
an inter-process lock, so two runs sharing one login cannot interleave their
write-backs or lose one to the other.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import shutil
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..utils.atomic_write import atomic_write_text
from ..utils.file_lock import held_exclusive_lock

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "CODEX_AUTH_FILENAME",
    "CodexAuthSeed",
    "codex_credential_store_mode",
    "seed_run_credential",
    "write_back_refreshed_credential",
]

logger = logging.getLogger(__name__)

CODEX_AUTH_FILENAME = "auth.json"

# What was copied, recorded beside the copy rather than carried in memory: the
# home outlives the call that built it, cleanup is reached from several paths,
# and a record on disk is readable by whichever of them gets there.
_SEED_FILENAME = ".vaultspec-codex-auth-seed.json"

# Serialises write-back across every process sharing one source login. Named
# next to the credential it guards, because that file - not this service's own
# state - is what two concurrent runs contend for.
_LOCK_FILENAME = ".vaultspec-codex-auth.lock"

_LOCK_TIMEOUT_SECONDS = 10.0

# Codex's own config key for where it keeps credentials. Reported when there is
# no credential file to seed from, because "no file" then means "kept elsewhere"
# rather than "not logged in", and the two call for different operator action.
_CREDENTIAL_STORE_KEY = "cli_auth_credentials_store"
_DEFAULT_CREDENTIAL_STORE = "auto"


@dataclass(frozen=True, slots=True)
class CodexAuthSeed:
    """The login a run home was seeded with, as recorded when it was copied."""

    source: Path
    digest: str
    last_refresh: str | None


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _restrict_file(path: Path) -> None:
    """Best-effort owner-only permissions on a credential file; never raises."""
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def codex_credential_store_mode(base_home: Path) -> str:
    """Return the credential store Codex is configured to use in *base_home*.

    Read from the operator's own config rather than assumed, because it decides
    whether a missing credential file is a missing login or a login held
    somewhere this service cannot copy from. An unreadable or silent config
    reports Codex's own default.
    """
    config = base_home / "config.toml"
    try:
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _DEFAULT_CREDENTIAL_STORE
    mode = parsed.get(_CREDENTIAL_STORE_KEY)
    return mode if isinstance(mode, str) and mode else _DEFAULT_CREDENTIAL_STORE


def _last_refresh(payload: bytes) -> datetime | None:
    """Read the credential's own refresh stamp, or ``None`` when it has none."""
    try:
        document = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(document, dict):
        return None
    stamp = document.get("last_refresh")
    if not isinstance(stamp, str) or not stamp:
        return None
    # Codex writes an RFC 3339 stamp with a trailing 'Z' and sub-second digits
    # beyond what fromisoformat accepted before 3.11; normalise the zone and clamp
    # the fraction to microseconds so a real stamp is never read as absent.
    text = stamp.strip().replace("Z", "+00:00")
    if "." in text:
        head, _, tail = text.partition(".")
        fraction = "".join(ch for ch in tail if ch.isdigit())[:6]
        zone = tail[len(fraction) :].lstrip("0123456789")
        text = f"{head}.{fraction or '0'}{zone}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _write_seed(run_home: Path, seed: CodexAuthSeed) -> None:
    (run_home / _SEED_FILENAME).write_text(
        json.dumps(
            {
                "source": str(seed.source),
                "digest": seed.digest,
                "last_refresh": seed.last_refresh,
            }
        ),
        encoding="utf-8",
    )


def _read_seed(run_home: Path) -> CodexAuthSeed | None:
    try:
        document = json.loads((run_home / _SEED_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    source = document.get("source")
    digest = document.get("digest")
    last_refresh = document.get("last_refresh")
    if not isinstance(source, str) or not isinstance(digest, str):
        return None
    return CodexAuthSeed(
        source=Path(source),
        digest=digest,
        last_refresh=last_refresh if isinstance(last_refresh, str) else None,
    )


def seed_run_credential(base_home: Path, run_home: Path) -> CodexAuthSeed | None:
    """Copy the login from *base_home* into *run_home*, recording what was copied.

    Returns the seed, or ``None`` when *base_home* holds no credential file. That
    case is reported rather than passed over: with the credential store set to
    keep tokens outside the home, the run is about to start with no login at all,
    and nothing downstream distinguishes that from a lane the operator never
    authenticated.
    """
    source = base_home / CODEX_AUTH_FILENAME
    # Absence is the reported case; anything else that goes wrong reading the
    # credential is a broken login home, and the caller unwinds its half-built
    # run home rather than starting a run on a guess about what it holds.
    if not source.exists():
        logger.warning(
            "Codex run home carries no copied login: %s holds no %s "
            "(credential store mode %r). The run will authenticate only from its "
            "environment; run 'codex login' or set the credential store to the "
            "file store if the turn fails unauthenticated.",
            base_home,
            CODEX_AUTH_FILENAME,
            codex_credential_store_mode(base_home),
        )
        return None
    payload = source.read_bytes()
    destination = run_home / CODEX_AUTH_FILENAME
    shutil.copy2(source, destination)
    # Defensive: pin the credential copy to owner-only regardless of the
    # source's mode (POSIX-effective; a no-op on Windows, where the temp tree is
    # already user-scoped).
    _restrict_file(destination)
    seed = CodexAuthSeed(
        source=source,
        digest=_digest(payload),
        last_refresh=(
            stamp.isoformat() if (stamp := _last_refresh(payload)) is not None else None
        ),
    )
    _write_seed(run_home, seed)
    return seed


@contextlib.contextmanager
def _credential_lock(
    source: Path, *, timeout_seconds: float = _LOCK_TIMEOUT_SECONDS
) -> Iterator[None]:
    """Hold the write-back lock for one source login.

    The lock file is named next to the credential it guards, because that file -
    not this service's own state - is what two concurrent runs contend for. The
    waiting policy is this caller's: a bounded wait, because the cleanup path it
    runs on must not be able to hang a run's teardown.
    """
    with held_exclusive_lock(
        source.parent / _LOCK_FILENAME, timeout_seconds=timeout_seconds
    ):
        yield


def write_back_refreshed_credential(
    run_home: Path, *, lock_timeout_seconds: float = _LOCK_TIMEOUT_SECONDS
) -> bool:
    """Return a credential Codex refreshed during the run to its source home.

    ``True`` when a refreshed credential was written back. Nothing is written
    when the home was never seeded, when the credential is byte-identical to what
    was seeded, or when the source has since been refreshed by another run to a
    STRICTLY NEWER state - the newest refresh is the only one the provider will
    still honour, so a run that has been overtaken must not restore its own.

    Failures are reported and swallowed: this runs on a cleanup path, and the
    consequence of raising here is an unreaped process tree, while the
    consequence of a lost write-back is a login the operator can repair.
    """
    seed = _read_seed(run_home)
    if seed is None:
        return False
    try:
        payload = (run_home / CODEX_AUTH_FILENAME).read_bytes()
    except OSError:
        return False
    if _digest(payload) == seed.digest:
        return False
    try:
        with _credential_lock(seed.source, timeout_seconds=lock_timeout_seconds):
            if _source_overtook_the_run(seed, payload):
                return False
            # The audited publication: fsynced, retried over a contention
            # window, and never leaving a temporary credential behind.
            atomic_write_text(
                seed.source,
                payload.decode("utf-8"),
                mode=0o600,
                newline="",
            )
    except (OSError, TimeoutError) as error:
        logger.error(
            "Codex refreshed its credential during the run and it could not be "
            "written back to %s (%s). The operator's login may now hold a spent "
            "refresh token; 'codex login' restores it.",
            seed.source,
            error,
        )
        return False
    logger.info(
        "Wrote the credential Codex refreshed during the run back to %s",
        seed.source,
    )
    return True


def _source_overtook_the_run(seed: CodexAuthSeed, payload: bytes) -> bool:
    """Whether the source login moved past what this run holds, under the lock."""
    try:
        current = seed.source.read_bytes()
    except OSError:
        return False
    if _digest(current) == seed.digest:
        return False
    current_stamp = _last_refresh(current)
    run_stamp = _last_refresh(payload)
    if current_stamp is None:
        # Nothing to compare against: the run holds a credential it watched being
        # refreshed, so it is the better of the two.
        return False
    if run_stamp is None or current_stamp > run_stamp:
        logger.info(
            "Left the Codex login at %s alone: it was refreshed by another run "
            "after this one was seeded",
            seed.source,
        )
        return True
    return False
