"""The one masking rule every provider subprocess diagnostic shares.

A failed child reports its own configuration, and configuration is where
credentials live, so any retained tail is a plausible place for a token to
surface. This file pins the redactor itself; the lanes that must CALL it are
pinned where they surface their text, because a helper passing its own tests
says nothing about a caller that stopped invoking it.
"""

from __future__ import annotations

import pytest

from .._subprocess import redact_secrets


@pytest.mark.parametrize(
    ("line", "must_not_contain"),
    [
        ("ANTHROPIC_AUTH_TOKEN=sk-ant-secret", "sk-ant-secret"),
        ("Authorization: Bearer sk-live-9f8e7d", "sk-live-9f8e7d"),
        ("OPENAI_API_KEY: sk-proj-zzz", "sk-proj-zzz"),
        ("my_password = hunter2", "hunter2"),
        ("VAULTSPEC_A2A_GATEWAY_TOKEN=abc123", "abc123"),
    ],
)
def test_credential_shaped_values_are_masked(line: str, must_not_contain: str) -> None:
    """The value goes; the name stays, so the line is still diagnostic."""
    redacted = redact_secrets(line)

    assert must_not_contain not in redacted
    assert "<redacted>" in redacted


@pytest.mark.parametrize(
    "line",
    [
        "connecting to 127.0.0.1:8766",
        "error: failed to start app-server",
        "plain diagnostic line with no secret",
    ],
)
def test_ordinary_diagnostics_survive_untouched(line: str) -> None:
    """Over-redaction would destroy the value the buffer exists to provide."""
    assert redact_secrets(line) == line


def test_the_redactor_is_not_inert() -> None:
    """A guard against the pattern silently matching nothing.

    This exact failure occurred during development: a stray control byte in the
    expression made it match nothing, so every line passed through unchanged
    while the code read as if it redacted.
    """
    assert redact_secrets("API_KEY=value") != "API_KEY=value"


def test_a_multi_line_block_is_masked_per_occurrence() -> None:
    """One caller hands over a whole captured block, not a single line.

    Every credential in the block must go and every ordinary line must stay:
    a redactor that stopped at the first match, or that swallowed the rest of
    the block after one, would pass a single-line check and fail here.
    """
    block = (
        "resolving requirements\n"
        "ANTHROPIC_AUTH_TOKEN=sk-ant-first\n"
        "connecting to 127.0.0.1:8766\n"
        "GATEWAY_SECRET=second-value\n"
        "server exited with code 3"
    )

    redacted = redact_secrets(block)

    assert "sk-ant-first" not in redacted
    assert "second-value" not in redacted
    assert redacted.count("<redacted>") == 2
    assert "resolving requirements" in redacted
    assert "connecting to 127.0.0.1:8766" in redacted
    assert "server exited with code 3" in redacted
