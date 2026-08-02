"""Programmatic refresh of the Gemini CLI's OAuth credentials.

Background
----------
The Gemini CLI stores its OAuth state in ``~/.gemini/oauth_creds.json`` using
the google-auth-library format (``access_token``, ``refresh_token``,
``expiry_date`` in Unix milliseconds, etc.).

When launched as a subprocess with piped stdin/stdout — which is exactly how
``AcpChatModel`` invokes ``gemini --experimental-acp`` — the CLI detects that
it is not running in a TTY and tries to start a browser-based auth flow if the
cached access_token is expired.  In headless mode (gemini-cli ≥ v0.18.0,
issue #13853) this causes a **silent hang**: the CLI blocks waiting for input
on stdin, which is occupied by the JSON-RPC pipe, so the ACP ``initialize``
handshake never arrives.

Fix
---
Refresh the access token **before** spawning the subprocess.  If the file
already contains a valid (non-expired) token the function returns immediately
with no network call.  If the token is expired it POSTs to Google's OAuth2
token endpoint using the public client credentials that are hardcoded in the
gemini-cli source (``packages/core/src/code_assist/oauth2.ts``).  This is
standard OAuth 2.0 for Installed Applications — the client_secret is
intentionally public per Google's specification.

References:
----------
- gemini-cli issue #13853: Silent hang on headless token refresh
- gemini-cli issue #12042: ACP mode prompts for login from Python subprocess
- gemini-cli/packages/core/src/code_assist/oauth2.ts (client credentials)
- google.oauth2 for Installed Applications:
  https://developers.google.com/identity/protocols/oauth2/native-app
"""

import asyncio
import contextlib
import errno
import json
import logging
import math
import os
import stat
import time
from collections.abc import Mapping
from pathlib import Path
from typing import NotRequired, TypedDict

import httpx
from pydantic import TypeAdapter, ValidationError

from ..control.config import settings
from ..desktop._platform_acl import harden_credential_file

__all__ = ["gemini_uses_env_auth", "refresh_gemini_token"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public client credentials — hardcoded in gemini-cli source, intentionally
# not secret (Google "installed application" OAuth 2.0 pattern).
# Source: gemini-cli/packages/core/src/code_assist/oauth2.ts
# ---------------------------------------------------------------------------
_CLIENT_ID = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
_CLIENT_SECRET = "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"
_TOKEN_URI = "https://oauth2.googleapis.com/token"

_GEMINI_DIR_NAME = ".gemini"
_CREDS_FILE_NAME = "oauth_creds.json"

# HTTP status code for success.
_HTTP_OK = 200

# How long to ride out a transient Windows sharing violation when renaming the
# refreshed credentials over the live file: the Gemini command-line interface
# may hold it open while this publishes.
_REPLACE_RETRY_SECONDS = 2.0
_REPLACE_RETRY_INTERVAL = 0.01

# A refresh can take a network round-trip, but it must not wait forever behind a
# dead or wedged peer process.  The operating-system releases advisory locks
# when the owning descriptor closes (including process exit).
_LOCK_ACQUIRE_SECONDS = 15.0
_LOCK_RETRY_INTERVAL = 0.05

# Serialises concurrent refresh attempts so two graph executions that both
# detect expired credentials do not race on the credentials file.
_refresh_lock = asyncio.Lock()

# Credential files belong to the Gemini CLI, so the untrusted JSON needs a
# complete recursive shape before this module reads or republishes any value.
type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class RefreshedToken(TypedDict):
    """Validated fields that may change the Gemini CLI credential record."""

    access_token: str
    expires_in: int | float
    token_type: NotRequired[str]
    refresh_token: NotRequired[str]


class _CredentialFileLock:
    """One adjacent, persistent advisory lock for a credential file."""

    def __init__(self, path: Path) -> None:
        self._path = path.with_name(f"{path.name}.lock")
        self._descriptor: int | None = None

    def acquire(self) -> None:
        """Acquire this file's cross-process lock within the bounded window."""
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        descriptor = os.open(self._path, flags, 0o600)
        try:
            _require_regular_lock_file(self._path, descriptor)
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\x00")
                os.fsync(descriptor)
            deadline = time.monotonic() + _LOCK_ACQUIRE_SECONDS
            while True:
                try:
                    _try_lock_descriptor(descriptor)
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Timed out waiting for Gemini OAuth credential "
                            "refresh lock."
                        ) from None
                    time.sleep(_LOCK_RETRY_INTERVAL)
                else:
                    self._descriptor = descriptor
                    return
        except BaseException:
            os.close(descriptor)
            raise

    def release(self) -> None:
        """Release the descriptor-held advisory lock without deleting its inode."""
        descriptor = self._descriptor
        if descriptor is None:
            return
        self._descriptor = None
        try:
            _unlock_descriptor(descriptor)
        finally:
            os.close(descriptor)


def _require_regular_lock_file(path: Path, descriptor: int) -> None:
    """Harden and verify the persistent non-secret lock file before locking it."""
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        raise OSError(f"Gemini OAuth lock path is not a regular file: {path}")
    harden_credential_file(path)


def _try_lock_descriptor(descriptor: int) -> None:
    """Attempt one non-blocking platform advisory lock acquisition."""
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_descriptor(descriptor: int) -> None:
    """Release one platform advisory lock held by *descriptor*."""
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


def gemini_uses_env_auth(env: dict[str, str] | None = None) -> bool:
    """Return True when Gemini is configured for non-interactive env auth."""
    source = env or os.environ
    return any(
        source.get(key)
        for key in (
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
        )
    )


def _default_creds_path(env: dict[str, str] | None = None) -> Path:
    """Return the Gemini OAuth credential path for the effective CLI home."""
    source = env or os.environ
    cli_home = source.get("GEMINI_CLI_HOME")
    if cli_home and cli_home.strip():
        return Path(cli_home) / _GEMINI_DIR_NAME / _CREDS_FILE_NAME
    return Path.home() / _GEMINI_DIR_NAME / _CREDS_FILE_NAME


def _is_expired(creds: Mapping[str, JsonValue]) -> bool:
    """Return True if the access token is missing or about to expire."""
    expiry_ms = creds.get("expiry_date")
    if (
        isinstance(expiry_ms, bool)
        or not isinstance(expiry_ms, int | float)
        or not math.isfinite(expiry_ms)
    ):
        return True
    return time.time() >= (expiry_ms / 1000.0) - settings.oauth_expiry_buffer_seconds


def _parse_json_object(raw: bytes, *, source: str) -> JsonObject:
    """Validate untrusted JSON bytes without exposing their contents in errors."""
    try:
        return _JSON_OBJECT.validate_json(raw)
    except ValidationError:
        raise RuntimeError(f"Invalid {source} JSON.") from None


def _required_token_string(payload: Mapping[str, JsonValue], field: str) -> str:
    """Read a required, non-empty token response string."""
    value = payload.get(field)
    if not isinstance(value, str) or not (normalized := value.strip()):
        raise RuntimeError(f"Gemini token refresh response lacks a valid {field}.")
    return normalized


def _required_token_number(payload: Mapping[str, JsonValue], field: str) -> int | float:
    """Read a finite credential lifetime beyond the proactive refresh window."""
    value = payload.get(field)
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= settings.oauth_expiry_buffer_seconds
    ):
        raise RuntimeError(f"Gemini token refresh response lacks a valid {field}.")
    return value


def _optional_token_string(payload: Mapping[str, JsonValue], field: str) -> str | None:
    """Read an optional token response string, rejecting malformed rotations."""
    if field not in payload:
        return None
    value = payload[field]
    if not isinstance(value, str) or not (normalized := value.strip()):
        raise RuntimeError(f"Gemini token refresh response has an invalid {field}.")
    return normalized


def _stored_refresh_token(creds: Mapping[str, JsonValue]) -> str:
    """Return the existing refresh token only when it is a non-blank string."""
    value = creds.get("refresh_token")
    if not isinstance(value, str) or not (normalized := value.strip()):
        raise RuntimeError(
            "No refresh_token in oauth_creds.json — cannot refresh headlessly. "
            "Run `gemini` interactively to re-authenticate."
        )
    return normalized


def _validated_refresh_token(payload: Mapping[str, JsonValue]) -> RefreshedToken:
    """Validate every response field before mutating credentials on disk."""
    token: RefreshedToken = {
        "access_token": _required_token_string(payload, "access_token"),
        "expires_in": _required_token_number(payload, "expires_in"),
    }
    token_type = _optional_token_string(payload, "token_type")
    if token_type is not None:
        token["token_type"] = token_type
    refresh_token = _optional_token_string(payload, "refresh_token")
    if refresh_token is not None:
        token["refresh_token"] = refresh_token
    return token


def _publish_credentials(path: Path, payload: str) -> None:
    """Write *payload* to a temporary file and rename it over *path*.

    Blocking: the caller offloads this to a worker thread.

    Three properties this needs and the plain write-then-rename it replaced did
    not have. The temporary carries the writing process id, so two processes
    refreshing the same credentials home cannot collide on the temporary itself
    and rename each other's half-written bytes over the target. The fsync is
    taken on the descriptor the bytes were written through rather than on a
    second one opened by path, so nothing can be substituted underneath it
    between the write and the flush. And the temporary is removed whenever the
    publication does not complete, so a failed refresh leaves the credentials
    directory as it found it instead of accumulating residue beside the file the
    Gemini command-line interface reads.

    This deliberately does not call the lifecycle package's audited writer:
    importing it here would execute ``vaultspec_a2a.lifecycle``, dragging the
    process registry, service discovery, and control configuration into a
    provider leaf whose import latency sits on the coding-agent command-line
    interface's tool-discovery window. The permission bits are left to the
    process umask, matching what this wrote before - tightening them is a
    decision about a file the Gemini command-line interface also owns, not a
    consequence of fixing the failure path.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, path)
    except BaseException:
        # Includes KeyboardInterrupt and SystemExit: an interrupted refresh must
        # not be the one case that leaves a temporary credential file behind.
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


def _replace_with_retry(tmp: Path, path: Path) -> None:
    """Rename *tmp* over *path*, riding out a transient sharing violation.

    ``os.replace`` is atomic, but on Windows a concurrent reader holding the
    target open can briefly deny it; retrying over a short bounded window turns a
    spurious failure into a successful publication.
    """
    deadline = time.monotonic() + _REPLACE_RETRY_SECONDS
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(_REPLACE_RETRY_INTERVAL)


async def refresh_gemini_token(
    creds_path: Path | None = None,
    *,
    env: dict[str, str] | None = None,
) -> None:
    """Ensure ``~/.gemini/oauth_creds.json`` contains a valid access token.

    If the token is still valid this is a no-op.  If it is expired (or will
    expire within ``_EXPIRY_BUFFER_S`` seconds) a fresh token is obtained from
    Google's token endpoint using the stored ``refresh_token`` and the public
    Gemini CLI client credentials, then written back atomically.

    This is an async function using ``httpx.AsyncClient`` to avoid blocking
    the event loop (H16 fix).

    If an official non-interactive auth path is already configured via
    ``GEMINI_API_KEY``, ``GOOGLE_API_KEY``, or
    ``GOOGLE_APPLICATION_CREDENTIALS``, this becomes a no-op.

    Args:
        creds_path: Path to the credentials file. Defaults to the effective
            Gemini CLI home, respecting ``GEMINI_CLI_HOME`` when set and
            otherwise using ``~/.gemini/oauth_creds.json``.
        env: Optional environment mapping used to detect env-based auth.

    Raises:
        FileNotFoundError: If the credentials file does not exist (i.e. the
            user has never authenticated interactively with ``gemini``).
        RuntimeError: If the credentials file has no ``refresh_token``, or if
            the token endpoint returns a non-200 response.
        httpx.TimeoutException: If the token endpoint does not respond within
            the configured timeout.
    """
    if gemini_uses_env_auth(env):
        logger.debug("Gemini env-based auth is configured; skipping OAuth refresh.")
        return

    creds_path = creds_path or _default_creds_path(env)

    if not creds_path.exists():
        raise FileNotFoundError(
            f"Gemini credentials not found at {creds_path}. "
            "Run `gemini` interactively at least once to authenticate."
        )

    async with _refresh_lock:
        # The persistent OS lock starts before the post-lock reread and ends only
        # after fsync + atomic publication.  That prevents separate VaultSpec
        # processes from racing a rotated refresh token over the same Gemini home.
        file_lock = _CredentialFileLock(creds_path)
        await asyncio.to_thread(file_lock.acquire)
        try:
            raw = await asyncio.to_thread(creds_path.read_bytes)
            creds = _parse_json_object(raw, source="Gemini OAuth credentials")

            # A peer process may have refreshed while this process waited for the
            # OS lock.  Reread after acquisition and return without a second HTTP
            # request when that publication is now fresh.
            if not _is_expired(creds):
                logger.debug("Gemini OAuth token is valid; skipping refresh.")
                return

            refresh_token = _stored_refresh_token(creds)
            logger.info("Gemini OAuth token expired; refreshing via token endpoint.")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    _TOKEN_URI,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": _CLIENT_ID,
                        "client_secret": _CLIENT_SECRET,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=15.0,
                )

            if response.status_code != _HTTP_OK:
                raise RuntimeError(
                    f"Gemini token refresh failed (HTTP {response.status_code}). "
                    "Check ~/.gemini/oauth_creds.json or re-authenticate interactively."
                ) from None

            token_data = _validated_refresh_token(
                _parse_json_object(
                    response.content, source="Gemini token refresh response"
                )
            )

            creds["access_token"] = token_data["access_token"]
            creds["expiry_date"] = int((time.time() + token_data["expires_in"]) * 1000)
            if "token_type" in token_data:
                creds["token_type"] = token_data["token_type"]
            # Google may rotate the refresh token — preserve the new one if provided.
            if "refresh_token" in token_data:
                creds["refresh_token"] = token_data["refresh_token"]

            # One offload for the whole publication: the write, the fsync that makes
            # it durable before the rename, and the rename itself are all blocking
            # filesystem work that must not run on the event loop.
            await asyncio.to_thread(
                _publish_credentials, creds_path, json.dumps(creds, indent=2)
            )

            logger.info(
                "Gemini OAuth token refreshed; new expiry in %ds.",
                token_data["expires_in"],
            )
        finally:
            await asyncio.to_thread(file_lock.release)
