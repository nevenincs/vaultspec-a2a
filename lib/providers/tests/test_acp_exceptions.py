"""Tests for ACP-specific exceptions and error codes.

Exercises the AcpErrorCode enum, AcpError base class formatting,
subclass hierarchy, and attribute preservation through raise/except.
"""

import pytest

from ..acp_exceptions import (
    AcpAuthError,
    AcpError,
    AcpErrorCode,
    AcpPromptError,
    AcpProtocolError,
    AcpSessionError,
)


# ---------------------------------------------------------------------------
# AcpErrorCode enum
# ---------------------------------------------------------------------------


class TestAcpErrorCode:
    """Tests for the AcpErrorCode IntEnum."""

    def test_standard_jsonrpc_codes(self) -> None:
        """All five standard JSON-RPC error codes are present with correct values."""
        assert AcpErrorCode.PARSE_ERROR == -32700
        assert AcpErrorCode.INVALID_REQUEST == -32600
        assert AcpErrorCode.METHOD_NOT_FOUND == -32601
        assert AcpErrorCode.INVALID_PARAMS == -32602
        assert AcpErrorCode.INTERNAL_ERROR == -32603

    def test_unknown_error_code(self) -> None:
        """The UNKNOWN_ERROR sentinel has value -1."""
        assert AcpErrorCode.UNKNOWN_ERROR == -1

    def test_codes_are_integers(self) -> None:
        """All members are ints (IntEnum)."""
        for member in AcpErrorCode:
            assert isinstance(member, int)

    def test_member_count(self) -> None:
        """Exactly 6 error codes defined."""
        expected_count = 6
        assert len(AcpErrorCode) == expected_count


# ---------------------------------------------------------------------------
# AcpError base class
# ---------------------------------------------------------------------------


class TestAcpError:
    """Tests for AcpError construction and message formatting."""

    def test_default_code_is_internal_error(self) -> None:
        """Default code when not specified is INTERNAL_ERROR."""
        err = AcpError("something failed")
        assert err.code == AcpErrorCode.INTERNAL_ERROR

    def test_message_format_basic(self) -> None:
        """str(err) includes the error code and message."""
        err = AcpError("test error", code=AcpErrorCode.PARSE_ERROR)
        text = str(err)
        assert "ACP Error" in text
        assert str(AcpErrorCode.PARSE_ERROR) in text
        assert "test error" in text

    def test_message_format_with_request_id(self) -> None:
        """Request ID is prepended when provided."""
        err = AcpError("fail", request_id="req-42")
        text = str(err)
        assert "(req-42)" in text

    def test_message_format_with_data(self) -> None:
        """Data is appended when provided."""
        err = AcpError("fail", data={"detail": "extra info"})
        text = str(err)
        assert "Data:" in text
        assert "extra info" in text

    def test_message_format_with_all_fields(self) -> None:
        """Full format with request_id, code, message, and data."""
        err = AcpError(
            "broken",
            code=AcpErrorCode.INVALID_PARAMS,
            data="details",
            request_id=1001,
        )
        text = str(err)
        assert "(1001)" in text
        assert str(AcpErrorCode.INVALID_PARAMS) in text
        assert "broken" in text
        assert "details" in text

    def test_attributes_stored(self) -> None:
        """All constructor args are accessible as attributes."""
        err = AcpError("msg", code=-999, data=[1, 2], request_id="r")
        assert err.message == "msg"
        assert err.code == -999
        assert err.data == [1, 2]
        assert err.request_id == "r"

    def test_is_exception(self) -> None:
        """AcpError is a subclass of Exception."""
        assert issubclass(AcpError, Exception)

    def test_raise_and_catch(self) -> None:
        """AcpError preserves attributes through raise/except."""
        with pytest.raises(AcpError) as exc_info:
            raise AcpError("boom", code=AcpErrorCode.METHOD_NOT_FOUND, request_id=42)
        err = exc_info.value
        assert err.message == "boom"
        assert err.code == AcpErrorCode.METHOD_NOT_FOUND
        assert err.request_id == 42


# ---------------------------------------------------------------------------
# Subclass hierarchy
# ---------------------------------------------------------------------------


class TestAcpSubclasses:
    """Tests for AcpError subclass hierarchy and catchability."""

    @pytest.mark.parametrize(
        "exc_cls",
        [AcpProtocolError, AcpSessionError, AcpPromptError, AcpAuthError],
        ids=["Protocol", "Session", "Prompt", "Auth"],
    )
    def test_is_subclass_of_acp_error(self, exc_cls: type[AcpError]) -> None:
        """Each subclass is an AcpError."""
        assert issubclass(exc_cls, AcpError)

    @pytest.mark.parametrize(
        "exc_cls",
        [AcpProtocolError, AcpSessionError, AcpPromptError, AcpAuthError],
        ids=["Protocol", "Session", "Prompt", "Auth"],
    )
    def test_subclass_caught_as_acp_error(self, exc_cls: type[AcpError]) -> None:
        """Subclass instances are catchable as AcpError."""
        with pytest.raises(AcpError):
            raise exc_cls("test")

    @pytest.mark.parametrize(
        "exc_cls",
        [AcpProtocolError, AcpSessionError, AcpPromptError, AcpAuthError],
        ids=["Protocol", "Session", "Prompt", "Auth"],
    )
    def test_subclass_inherits_formatting(self, exc_cls: type[AcpError]) -> None:
        """Subclasses inherit _format_message from AcpError."""
        err = exc_cls("sub error", code=AcpErrorCode.PARSE_ERROR, request_id="r1")
        text = str(err)
        assert "ACP Error" in text
        assert "sub error" in text
        assert "(r1)" in text

    def test_siblings_not_cross_catchable(self) -> None:
        """AcpProtocolError is not caught by AcpSessionError."""
        with pytest.raises(AcpProtocolError):
            try:
                raise AcpProtocolError("proto fail")
            except AcpSessionError:
                pytest.fail("AcpSessionError should not catch AcpProtocolError")

    def test_subclass_attributes_preserved(self) -> None:
        """Subclass instances preserve all AcpError attributes."""
        err = AcpAuthError(
            "auth failed",
            code=AcpErrorCode.INVALID_REQUEST,
            data={"reason": "expired"},
            request_id="auth-1",
        )
        assert err.message == "auth failed"
        assert err.code == AcpErrorCode.INVALID_REQUEST
        assert err.data == {"reason": "expired"}
        assert err.request_id == "auth-1"
