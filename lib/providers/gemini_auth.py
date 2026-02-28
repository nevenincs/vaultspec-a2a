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
import json
import logging
import os
import time

from pathlib import Path

import httpx


__all__ = ["refresh_gemini_token"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public client credentials — hardcoded in gemini-cli source, intentionally
# not secret (Google "installed application" OAuth 2.0 pattern).
# Source: gemini-cli/packages/core/src/code_assist/oauth2.ts
# ---------------------------------------------------------------------------
_CLIENT_ID = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
_CLIENT_SECRET = "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"
_TOKEN_URI = "https://oauth2.googleapis.com/token"

# Refresh this many seconds before the actual expiry to absorb clock skew and
# subprocess startup latency.
_EXPIRY_BUFFER_S = 120

_CREDS_PATH = Path.home() / ".gemini" / "oauth_creds.json"

# HTTP status code for success.
_HTTP_OK = 200


def _is_expired(creds: dict) -> bool:
    """Return True if the access token is missing or about to expire."""
    expiry_ms = creds.get("expiry_date")
    if expiry_ms is None:
        return True
    return time.time() >= (expiry_ms / 1000.0) - _EXPIRY_BUFFER_S


def _fsync_file(path: Path) -> None:
    """Open a file read-only and fsync it to flush OS write-back cache."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


async def refresh_gemini_token(creds_path: Path = _CREDS_PATH) -> None:
    """Ensure ``~/.gemini/oauth_creds.json`` contains a valid access token.

    If the token is still valid this is a no-op.  If it is expired (or will
    expire within ``_EXPIRY_BUFFER_S`` seconds) a fresh token is obtained from
    Google's token endpoint using the stored ``refresh_token`` and the public
    Gemini CLI client credentials, then written back atomically.

    This is an async function using ``httpx.AsyncClient`` to avoid blocking
    the event loop (H16 fix).

    Args:
        creds_path: Path to the credentials file.  Defaults to
            ``~/.gemini/oauth_creds.json``.

    Raises:
        FileNotFoundError: If the credentials file does not exist (i.e. the
            user has never authenticated interactively with ``gemini``).
        RuntimeError: If the credentials file has no ``refresh_token``, or if
            the token endpoint returns a non-200 response.
        httpx.TimeoutException: If the token endpoint does not respond within
            the configured timeout.
    """
    if not creds_path.exists():
        raise FileNotFoundError(
            f"Gemini credentials not found at {creds_path}. "
            "Run `gemini` interactively at least once to authenticate."
        )

    creds: dict = json.loads(creds_path.read_text(encoding="utf-8"))

    if not _is_expired(creds):
        logger.debug("Gemini OAuth token is valid; skipping refresh.")
        return

    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "No refresh_token in oauth_creds.json — cannot refresh headlessly. "
            "Run `gemini` interactively to re-authenticate."
        )

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

    token_data = response.json()

    creds["access_token"] = token_data["access_token"]
    creds["expiry_date"] = int((time.time() + token_data["expires_in"]) * 1000)
    if "token_type" in token_data:
        creds["token_type"] = token_data["token_type"]
    # Google may rotate the refresh token — preserve the new one if provided.
    if "refresh_token" in token_data:
        creds["refresh_token"] = token_data["refresh_token"]

    # Atomic write: write to .tmp, fsync, then rename to avoid partial reads.
    tmp = creds_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(creds, indent=2), encoding="utf-8")
    # PROV-L4: fsync via to_thread so blocking syscall doesn't stall event loop.
    # M16: fsync before rename so data is durable even on power failure.
    await asyncio.to_thread(_fsync_file, tmp)
    tmp.replace(creds_path)

    logger.info(
        "Gemini OAuth token refreshed; new expiry in %ds.",
        token_data["expires_in"],
    )
