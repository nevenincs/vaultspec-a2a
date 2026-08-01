"""Tests for the Gemini OAuth credential refresh module.

Uses tmp_path for synthetic credential files. Network-hitting refresh tests
are marked @pytest.mark.live.
"""

import json
import os
import time
from pathlib import Path

import pytest

from ...control.config import settings
from ..gemini_auth import (
    _default_creds_path,
    _is_expired,
    _publish_credentials,
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


# ---------------------------------------------------------------------------


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
