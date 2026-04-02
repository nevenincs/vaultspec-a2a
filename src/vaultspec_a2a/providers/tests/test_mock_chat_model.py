"""Focused regressions for VidaiMock chunk parsing."""

from vaultspec_a2a.providers.mock_chat_model import (
    _extract_chunk_text,
    _extract_tool_calls,
)


def test_extract_chunk_text_accepts_top_level_string_chunks() -> None:
    """VidaiMock can stream bare JSON strings for simple static responses."""
    assert _extract_chunk_text("mock-coder-human ") == "mock-coder-human "


def test_extract_chunk_text_accepts_serialized_content_block_strings() -> None:
    """Serialized content-block strings must decode to route text."""
    chunk = '[{"type":"text","text":"mock-coder-human"}] '
    assert _extract_chunk_text(chunk) == "mock-coder-human"


def test_extract_tool_calls_accepts_string_wrapped_json_arrays() -> None:
    """String-wrapped VidaiMock tool-call arrays must still be decoded."""
    chunk = (
        '[{"function":{"arguments":"{\\"description\\": \\"Approve\\"}",'
        '"name":"session_request_permission"},"id":"call_0","type":"function"}]'
    )

    tool_calls = _extract_tool_calls(chunk)

    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "session_request_permission"
