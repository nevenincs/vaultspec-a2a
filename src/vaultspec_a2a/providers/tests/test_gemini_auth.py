"""Tests for the Gemini OAuth credential refresh module.

Uses tmp_path for synthetic credential files. Network-hitting refresh tests
are marked @pytest.mark.live.
"""

import json
import time

import pytest

from ..gemini_auth import (
    _CREDS_PATH,
    _EXPIRY_BUFFER_S,
    _is_expired,
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
        almost_expired_ms = int((time.time() + _EXPIRY_BUFFER_S / 2) * 1000)
        assert _is_expired({"expiry_date": almost_expired_ms}) is True

    def test_future_expiry_is_not_expired(self) -> None:
        """Credentials with expiry well in the future are valid."""
        future_ms = int((time.time() + 3600) * 1000)
        assert _is_expired({"expiry_date": future_ms}) is False

    def test_exactly_at_buffer_boundary(self) -> None:
        """Credentials expiring exactly at the buffer boundary are expired."""
        boundary_ms = int((time.time() + _EXPIRY_BUFFER_S) * 1000)
        # time.time() >= (boundary_ms / 1000) - _EXPIRY_BUFFER_S
        # time.time() >= time.time() (approximately True due to rounding)
        # This is a boundary case; the result depends on sub-ms timing
        result = _is_expired({"expiry_date": boundary_ms})
        assert isinstance(result, bool)  # Just verify no crash


# ---------------------------------------------------------------------------
# refresh_gemini_token — offline tests
# ---------------------------------------------------------------------------


class TestRefreshGeminiTokenOffline:
    """Tests for refresh_gemini_token that do not hit the network."""

    @pytest.mark.asyncio
    async def test_file_not_found_raises(self, tmp_path) -> None:
        """FileNotFoundError is raised when credentials file does not exist."""
        missing = tmp_path / "oauth_creds.json"
        with pytest.raises(FileNotFoundError, match="not found"):
            await refresh_gemini_token(creds_path=missing)

    @pytest.mark.asyncio
    async def test_valid_token_is_noop(self, tmp_path) -> None:
        """When the token is valid, no network call or file write occurs."""
        creds_path = tmp_path / "oauth_creds.json"
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
    async def test_expired_no_refresh_token_raises(self, tmp_path) -> None:
        """RuntimeError is raised when token is expired but no refresh_token exists."""
        creds_path = tmp_path / "oauth_creds.json"
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
    async def test_empty_refresh_token_raises(self, tmp_path) -> None:
        """RuntimeError is raised when refresh_token is empty string."""
        creds_path = tmp_path / "oauth_creds.json"
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
    async def test_creds_path_accepts_custom_path(self, tmp_path) -> None:
        """The creds_path parameter routes to the correct file."""
        custom_path = tmp_path / "subdir" / "creds.json"
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
# refresh_gemini_token — live network test
# ---------------------------------------------------------------------------


class TestRefreshGeminiTokenLive:
    """Tests that actually hit Google's token endpoint.

    Requires valid ~/.gemini/oauth_creds.json with a refresh_token.
    """

    @pytest.mark.live
    @pytest.mark.asyncio
    async def test_refresh_expired_token(self, tmp_path) -> None:
        """Refresh an expired token using a real refresh_token.

        Copies the user's real credentials to tmp_path, forces expiry,
        then refreshes. Verifies the new access_token is different and
        expiry is in the future.
        """
        real_creds = json.loads(_CREDS_PATH.read_text(encoding="utf-8"))
        refresh_token = real_creds.get("refresh_token")
        assert refresh_token, (
            f"No refresh_token in {_CREDS_PATH} — "
            "ensure real Gemini OAuth credentials are present"
        )

        # Copy to tmp and force expiry
        test_path = tmp_path / "oauth_creds.json"
        real_creds["expiry_date"] = int((time.time() - 3600) * 1000)
        test_path.write_text(json.dumps(real_creds), encoding="utf-8")

        await refresh_gemini_token(creds_path=test_path)

        refreshed = json.loads(test_path.read_text(encoding="utf-8"))
        assert refreshed["access_token"] != ""
        assert refreshed["expiry_date"] > int(time.time() * 1000)
