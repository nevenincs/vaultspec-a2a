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


def test_json_shaped_credentials_are_masked() -> None:
    """A config dumped as JSON must not carry its credential into a tail.

    The pattern originally expected whitespace between an introducing name and
    its separator, so ``"apiKey": "sk-..."`` - a quote sitting where the space
    was expected - passed through untouched. That is not hypothetical: it is
    exactly what `kimi provider list --json` prints, so any diagnostic that
    retained that output would have retained a live key. Both spacings are
    asserted because a compact dump has no space after the colon either.
    """
    secret = "sk-live-value-must-not-appear"
    for line in (
        f'  "apiKey": "{secret}"',
        f'{{"apiKey":"{secret}"}}',
        f"'password': '{secret}'",
    ):
        masked = redact_secrets(line)
        assert secret not in masked, masked
        assert "<redacted>" in masked, masked


def test_masking_preserves_the_quoting_it_found() -> None:
    """A masked JSON value still reads as JSON, so a tail stays parseable."""
    masked = redact_secrets('{"apiKey":"sk-secret"}')
    assert masked == '{"apiKey":"<redacted>"}'


def test_text_without_a_credential_name_is_untouched() -> None:
    """Masking keys on the introducing NAME, so ordinary output is unharmed."""
    line = "listing 4 models for provider moonshot-ai"
    assert redact_secrets(line) == line
