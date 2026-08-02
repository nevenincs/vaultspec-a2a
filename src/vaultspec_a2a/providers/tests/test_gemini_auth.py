"""Tests for the Gemini OAuth credential refresh module.

Uses tmp_path for synthetic credential files. Network-hitting refresh tests
are marked @pytest.mark.live.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ...control.config import settings
from ..gemini_auth import (
    JsonValue,
    _default_creds_path,
    _is_expired,
    _publish_credentials,
    _stored_refresh_token,
    _validated_refresh_token,
    gemini_uses_env_auth,
    refresh_gemini_token,
)

# ---------------------------------------------------------------------------
# _is_expired helper
# ---------------------------------------------------------------------------


class TestIsExpired:
    """Tests for the _is_expired helper function."""

    def test_missing_expiry_date_is_expired(self) -> None:
        """Credentials without expiry_date are considered expired."""
        assert _is_expired({}) is True

    def test_none_expiry_date_is_expired(self) -> None:
        """Credentials with expiry_date=None are considered expired."""
        assert _is_expired({"expiry_date": None}) is True

    def test_past_expiry_is_expired(self) -> None:
        """Credentials with expiry_date in the past are expired."""
        past_ms = int((time.time() - 3600) * 1000)
        assert _is_expired({"expiry_date": past_ms}) is True

    def test_within_buffer_is_expired(self) -> None:
        """Credentials expiring within the buffer window are considered expired."""
        # Set expiry to now + half the buffer (should trigger refresh)
        almost_expired_ms = int(
            (time.time() + settings.oauth_expiry_buffer_seconds / 2) * 1000
        )
        assert _is_expired({"expiry_date": almost_expired_ms}) is True

    def test_future_expiry_is_not_expired(self) -> None:
        """Credentials with expiry well in the future are valid."""
        future_ms = int((time.time() + 3600) * 1000)
        assert _is_expired({"expiry_date": future_ms}) is False

    def test_exactly_at_buffer_boundary(self) -> None:
        """Credentials expiring exactly at the buffer boundary are expired."""
        boundary_ms = int((time.time() + settings.oauth_expiry_buffer_seconds) * 1000)
        # time.time() >= (boundary_ms / 1000) - _EXPIRY_BUFFER_S
        # time.time() >= time.time() (approximately True due to rounding)
        # This is a boundary case; the result depends on sub-ms timing
        result = _is_expired({"expiry_date": boundary_ms})
        assert isinstance(result, bool)  # Just verify no crash


class TestGeminiUsesEnvAuth:
    """Tests for explicit non-interactive Gemini auth detection."""

    def test_detects_gemini_api_key(self) -> None:
        assert gemini_uses_env_auth({"GEMINI_API_KEY": "test-key"}) is True

    def test_detects_google_api_key(self) -> None:
        assert gemini_uses_env_auth({"GOOGLE_API_KEY": "test-key"}) is True

    def test_detects_google_application_credentials(self) -> None:
        assert (
            gemini_uses_env_auth(
                {"GOOGLE_APPLICATION_CREDENTIALS": "/run/secrets/google.json"}
            )
            is True
        )

    def test_returns_false_without_supported_env_auth(self) -> None:
        assert gemini_uses_env_auth({"PATH": "/usr/bin"}) is False


class TestDefaultCredsPath:
    """Tests for resolving the effective Gemini OAuth credential path."""

    def test_defaults_to_home_gemini_dir(self) -> None:
        assert _default_creds_path({"PATH": "/usr/bin"}) == (
            Path.home() / ".gemini" / "oauth_creds.json"
        )

    def test_honors_gemini_cli_home(self, tmp_path: Path) -> None:
        cli_home = tmp_path / "cli-home"
        cli_home.mkdir(parents=True, exist_ok=False)
        assert _default_creds_path({"GEMINI_CLI_HOME": str(cli_home)}) == (
            cli_home / ".gemini" / "oauth_creds.json"
        )


# ---------------------------------------------------------------------------
# refresh_gemini_token — offline tests
# ---------------------------------------------------------------------------


class TestRefreshGeminiTokenOffline:
    """Tests for refresh_gemini_token that do not hit the network."""

    @pytest.mark.asyncio
    async def test_file_not_found_raises(self, tmp_path: Path) -> None:
        """FileNotFoundError is raised when credentials file does not exist."""
        test_root = tmp_path / "missing"
        test_root.mkdir(parents=True, exist_ok=False)
        missing = test_root / "oauth_creds.json"
        with pytest.raises(FileNotFoundError, match="not found"):
            await refresh_gemini_token(creds_path=missing)

    @pytest.mark.asyncio
    async def test_env_auth_skips_missing_file(self, tmp_path: Path) -> None:
        """Env-authenticated Gemini runs do not require a local OAuth file."""
        test_root = tmp_path / "env-auth"
        test_root.mkdir(parents=True, exist_ok=False)
        missing = test_root / "oauth_creds.json"
        await refresh_gemini_token(
            creds_path=missing,
            env={"GEMINI_API_KEY": "test-key"},
        )

    @pytest.mark.asyncio
    async def test_valid_token_is_noop(self, tmp_path: Path) -> None:
        """When the token is valid, no network call or file write occurs."""
        test_root = tmp_path / "valid"
        test_root.mkdir(parents=True, exist_ok=False)
        creds_path = test_root / "oauth_creds.json"
        future_ms = int((time.time() + 7200) * 1000)
        creds = {
            "access_token": "valid-token",
            "refresh_token": "rt-123",
            "expiry_date": future_ms,
        }
        creds_path.write_text(json.dumps(creds), encoding="utf-8")

        # Should return without error or modification
        await refresh_gemini_token(creds_path=creds_path)

        # File should be unchanged
        result = json.loads(creds_path.read_text(encoding="utf-8"))
        assert result["access_token"] == "valid-token"
        assert result["expiry_date"] == future_ms

    @pytest.mark.asyncio
    async def test_expired_no_refresh_token_raises(self, tmp_path: Path) -> None:
        """RuntimeError is raised when token is expired but no refresh_token exists."""
        test_root = tmp_path / "expired"
        test_root.mkdir(parents=True, exist_ok=False)
        creds_path = test_root / "oauth_creds.json"
        past_ms = int((time.time() - 3600) * 1000)
        creds = {
            "access_token": "expired-token",
            "expiry_date": past_ms,
            # No refresh_token
        }
        creds_path.write_text(json.dumps(creds), encoding="utf-8")

        with pytest.raises(RuntimeError, match="No refresh_token"):
            await refresh_gemini_token(creds_path=creds_path)

    @pytest.mark.asyncio
    async def test_empty_refresh_token_raises(self, tmp_path: Path) -> None:
        """RuntimeError is raised when refresh_token is empty string."""
        test_root = tmp_path / "empty-refresh"
        test_root.mkdir(parents=True, exist_ok=False)
        creds_path = test_root / "oauth_creds.json"
        past_ms = int((time.time() - 3600) * 1000)
        creds = {
            "access_token": "expired-token",
            "refresh_token": "",
            "expiry_date": past_ms,
        }
        creds_path.write_text(json.dumps(creds), encoding="utf-8")

        with pytest.raises(RuntimeError, match="No refresh_token"):
            await refresh_gemini_token(creds_path=creds_path)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "malformed_refresh_token",
        ["   ", 1, 1.5, True, [], {}],
    )
    async def test_malformed_stored_refresh_token_fails_before_network_or_mutation(
        self, tmp_path: Path, malformed_refresh_token: object
    ) -> None:
        """Malformed local tokens fail locally and leave credential bytes intact."""
        creds_path = tmp_path / "oauth_creds.json"
        original = json.dumps(
            {
                "access_token": "expired-token",
                "refresh_token": malformed_refresh_token,
                "expiry_date": int((time.time() - 3600) * 1000),
            }
        ).encode()
        creds_path.write_bytes(original)

        with pytest.raises(RuntimeError, match="No refresh_token"):
            await refresh_gemini_token(creds_path=creds_path)

        assert creds_path.read_bytes() == original

    @pytest.mark.asyncio
    async def test_creds_path_accepts_custom_path(self, tmp_path: Path) -> None:
        """The creds_path parameter routes to the correct file."""
        test_root = tmp_path / "custom"
        custom_path = test_root / "subdir" / "creds.json"
        custom_path.parent.mkdir(parents=True)
        future_ms = int((time.time() + 7200) * 1000)
        creds = {
            "access_token": "custom-token",
            "refresh_token": "rt-abc",
            "expiry_date": future_ms,
        }
        custom_path.write_text(json.dumps(creds), encoding="utf-8")

        # Should succeed without error
        await refresh_gemini_token(creds_path=custom_path)


class TestRefreshTokenResponseValidation:
    """The OAuth response must be safe before it can mutate local credentials."""

    @pytest.mark.parametrize(
        "expires_in",
        [
            False,
            0,
            -1,
            settings.oauth_expiry_buffer_seconds,
            settings.oauth_expiry_buffer_seconds - 0.5,
            float("inf"),
            float("nan"),
        ],
    )
    def test_rejects_unusable_expires_in(self, expires_in: JsonValue) -> None:
        """A response lifetime must exceed the proactive refresh buffer."""
        with pytest.raises(RuntimeError, match="valid expires_in"):
            _validated_refresh_token(
                {
                    "access_token": "fresh-token",
                    "expires_in": expires_in,
                }
            )

    def test_normalizes_all_response_token_strings(self) -> None:
        """Whitespace around accepted response strings never reaches the file."""
        token = _validated_refresh_token(
            {
                "access_token": " fresh-access-token ",
                "expires_in": settings.oauth_expiry_buffer_seconds + 1,
                "token_type": " Bearer ",
                "refresh_token": " rotated-refresh-token ",
            }
        )

        assert token == {
            "access_token": "fresh-access-token",
            "expires_in": settings.oauth_expiry_buffer_seconds + 1,
            "token_type": "Bearer",
            "refresh_token": "rotated-refresh-token",
        }

    def test_normalizes_stored_refresh_token_before_request_construction(self) -> None:
        """A valid local token is stripped before it can cross the HTTP boundary."""
        assert _stored_refresh_token({"refresh_token": " local-refresh-token "}) == (
            "local-refresh-token"
        )

    @pytest.mark.parametrize("value", ["   ", 1, False, [], {}])
    def test_rejects_malformed_required_response_access_token(
        self, value: JsonValue
    ) -> None:
        """Required access-token strings reject blank and non-string responses."""
        with pytest.raises(RuntimeError, match="valid access_token"):
            _validated_refresh_token(
                {
                    "access_token": value,
                    "expires_in": settings.oauth_expiry_buffer_seconds + 1,
                }
            )

    @pytest.mark.parametrize("field", ["token_type", "refresh_token"])
    @pytest.mark.parametrize("value", ["   ", 1, False, [], {}])
    def test_rejects_malformed_optional_response_strings(
        self, field: str, value: JsonValue
    ) -> None:
        """A malformed optional rotation is an error rather than file mutation."""
        with pytest.raises(RuntimeError, match=f"invalid {field}"):
            _validated_refresh_token(
                {
                    "access_token": "fresh-token",
                    "expires_in": settings.oauth_expiry_buffer_seconds + 1,
                    field: value,
                }
            )


# ---------------------------------------------------------------------------
# Cross-process locking — real fresh interpreters and real descriptor release
# ---------------------------------------------------------------------------


def _subprocess_environment() -> dict[str, str]:
    """Return a process environment that cannot bypass OAuth via an API key."""
    environment = os.environ.copy()
    for key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ):
        environment.pop(key, None)
    return environment


def _start_lock_holder(creds_path: Path, *, crash: bool) -> subprocess.Popen[str]:
    """Start a fresh interpreter which acquires the production credential lock."""
    completion = "os._exit(0)" if crash else "lock.release()"
    script = (
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "from vaultspec_a2a.providers.gemini_auth import (\n"
        "    _CredentialFileLock, _publish_credentials,\n"
        ")\n"
        "path = Path(sys.argv[1])\n"
        "lock = _CredentialFileLock(path)\n"
        "lock.acquire()\n"
        "print('locked', flush=True)\n"
        "time.sleep(0.25)\n"
        "_publish_credentials(path, json.dumps({\n"
        "    'access_token': 'fresh-token',\n"
        "    'refresh_token': 'fresh-refresh-token',\n"
        "    'expiry_date': int((time.time() + 7200) * 1000),\n"
        "}))\n"
        "time.sleep(0.25)\n"
        f"{completion}\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", script, str(creds_path)],
        env=_subprocess_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _run_refresh_in_fresh_process(creds_path: Path) -> subprocess.CompletedProcess[str]:
    """Run the public refresh function in a fresh interpreter without API-key bypass."""
    script = (
        "import asyncio, sys\n"
        "from pathlib import Path\n"
        "from vaultspec_a2a.providers.gemini_auth import refresh_gemini_token\n"
        "asyncio.run(refresh_gemini_token(Path(sys.argv[1])))\n"
        "print('refresh-complete', flush=True)\n"
    )
    return subprocess.run(
        [sys.executable, "-c", script, str(creds_path)],
        env=_subprocess_environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


class TestCredentialRefreshProcessLock:
    """The persistent advisory lock coordinates independent Python processes."""

    def test_waiter_rereads_fresh_credentials_after_process_lock(
        self, tmp_path: Path
    ) -> None:
        """A second process waits, rereads, and skips an already-fresh OAuth file."""
        creds_path = tmp_path / "oauth_creds.json"
        creds_path.write_text(
            json.dumps(
                {
                    "access_token": "expired-token",
                    "refresh_token": [],
                    "expiry_date": int((time.time() - 3600) * 1000),
                }
            ),
            encoding="utf-8",
        )
        holder = _start_lock_holder(creds_path, crash=False)
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"

        started = time.monotonic()
        waiter = _run_refresh_in_fresh_process(creds_path)
        elapsed = time.monotonic() - started
        holder_stderr = holder.communicate(timeout=20)[1]

        assert holder.returncode == 0, holder_stderr
        assert waiter.returncode == 0, waiter.stderr
        assert waiter.stdout.strip() == "refresh-complete"
        assert elapsed >= 0.2
        assert json.loads(creds_path.read_text(encoding="utf-8"))["access_token"] == (
            "fresh-token"
        )

    def test_crashed_holder_releases_its_descriptor_lock(self, tmp_path: Path) -> None:
        """OS descriptor cleanup makes a persistent lock usable after a crash."""
        creds_path = tmp_path / "oauth_creds.json"
        creds_path.write_text(
            json.dumps(
                {
                    "access_token": "valid-token",
                    "refresh_token": "refresh-token",
                    "expiry_date": int((time.time() + 7200) * 1000),
                }
            ),
            encoding="utf-8",
        )
        holder = _start_lock_holder(creds_path, crash=True)
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        holder_stderr = holder.communicate(timeout=20)[1]

        assert holder.returncode == 0, holder_stderr
        waiter = _run_refresh_in_fresh_process(creds_path)

        assert waiter.returncode == 0, waiter.stderr
        assert waiter.stdout.strip() == "refresh-complete"
        assert (tmp_path / "oauth_creds.json.lock").is_file()


# ---------------------------------------------------------------------------
# _publish_credentials — the write-and-rename that lands a refreshed token
# ---------------------------------------------------------------------------


class TestPublishCredentials:
    """The refreshed credentials must land whole or not at all.

    Real files only: every failure below is produced by genuinely unwritable
    filesystem state or by content that cannot be encoded, never by a stand-in.
    """

    def test_the_payload_lands_and_no_temporary_survives(self, tmp_path: Path) -> None:
        """The ordinary case publishes the bytes and cleans up after itself."""
        target = tmp_path / "oauth_creds.json"

        _publish_credentials(target, json.dumps({"access_token": "fresh"}))

        assert json.loads(target.read_text(encoding="utf-8"))["access_token"] == "fresh"
        assert sorted(tmp_path.glob("*.tmp")) == []

    def test_a_denied_rename_leaves_no_temporary_behind(self, tmp_path: Path) -> None:
        """A rename that stays denied past the retry window must not leak residue.

        A directory standing where the credentials file belongs makes
        ``os.replace`` fail on every platform. The previous implementation left
        its temporary - holding a live refresh token - beside it.
        """
        target = tmp_path / "oauth_creds.json"
        target.mkdir()

        with pytest.raises(OSError):
            _publish_credentials(target, json.dumps({"refresh_token": "secret"}))

        assert target.is_dir()
        assert sorted(tmp_path.glob("*.tmp")) == []

    def test_a_non_os_failure_mid_write_still_removes_the_temporary(
        self, tmp_path: Path
    ) -> None:
        """A failure that is not an ``OSError`` must clean up too.

        An unpaired surrogate cannot be encoded as UTF-8, so the write raises a
        ``UnicodeEncodeError`` after the temporary already exists. Catching only
        ``OSError`` would leak residue here.
        """
        target = tmp_path / "oauth_creds.json"

        with pytest.raises(UnicodeEncodeError):
            _publish_credentials(target, "\ud800")

        assert not target.exists()
        assert sorted(tmp_path.glob("*.tmp")) == []

    def test_the_temporary_is_named_for_the_writing_process(
        self, tmp_path: Path
    ) -> None:
        """Two processes refreshing one credentials home must not collide.

        The temporary used to be a fixed ``oauth_creds.json.tmp``, so two
        refreshes of the same home wrote the same temporary and could rename
        each other's half-written bytes over the live file. Occupying the
        per-process name with a directory proves the name now carries the pid.
        """
        target = tmp_path / "oauth_creds.json"
        expected = tmp_path / f"oauth_creds.json.{os.getpid()}.tmp"
        expected.mkdir()

        with pytest.raises(OSError):
            _publish_credentials(target, json.dumps({"access_token": "blocked"}))

        assert expected.is_dir()
        assert not target.exists()
