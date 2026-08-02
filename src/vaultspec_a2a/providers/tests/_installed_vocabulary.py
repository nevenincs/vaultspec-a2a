"""Read each served lane's wire error vocabulary from its INSTALLED adapter.

A hand-copied list of discriminators passes forever, including on the day the
adapter adds a member the mapper has never seen - which is precisely the drift
these readers exist to catch. So the vocabulary is read from the artefact that
actually executes: the agent SDK's shipped type declaration for the ACP lane,
and the app-server's own generated protocol schema for the Codex lane.

Each reader raises when the installed artefact is absent or has changed shape,
so a caller can convert that into a skip naming the missing prerequisite rather
than silently asserting over an empty set.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "MissingInstalledVocabularyError",
    "acp_error_kinds",
    "acp_sdk_types_path",
]


class MissingInstalledVocabularyError(RuntimeError):
    """The installed adapter artefact a vocabulary is read from is unavailable."""


def _repo_root() -> Path:
    # src/vaultspec_a2a/providers/tests/_installed_vocabulary.py -> repo root
    return Path(__file__).resolve().parents[4]


def acp_sdk_types_path() -> Path:
    """Return the installed agent SDK type declaration the ACP lane runs against."""
    return (
        _repo_root()
        / "node_modules"
        / "@anthropic-ai"
        / "claude-agent-sdk"
        / "sdk.d.ts"
    )


_ACP_ERROR_KIND_DECLARATION = re.compile(
    r"declare type SDKAssistantMessageError\s*=\s*([^;]+);"
)
_STRING_LITERAL = re.compile(r"'([a-z0-9_]+)'")


def acp_error_kinds() -> frozenset[str]:
    """Return the ACP lane's closed ``errorKind`` vocabulary, as installed.

    The adapter attaches the kind as ``data.errorKind`` on its JSON-RPC failure
    frames, drawing it from the agent SDK's ``SDKAssistantMessageError`` union.
    That union declaration is parsed here rather than restated, so a member
    added upstream shows up as an unmapped kind instead of passing unnoticed.
    """
    types_path = acp_sdk_types_path()
    try:
        source = types_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MissingInstalledVocabularyError(
            "the installed @anthropic-ai/claude-agent-sdk type declaration is "
            f"unavailable at {types_path} (run the project's npm install)"
        ) from exc

    declaration = _ACP_ERROR_KIND_DECLARATION.search(source)
    if declaration is None:
        raise MissingInstalledVocabularyError(
            "the installed agent SDK no longer declares SDKAssistantMessageError "
            f"in {types_path}; the ACP error-kind vocabulary moved"
        )
    kinds = frozenset(_STRING_LITERAL.findall(declaration.group(1)))
    if not kinds:
        raise MissingInstalledVocabularyError(
            "the installed SDKAssistantMessageError declaration lists no string "
            f"members in {types_path}"
        )
    return kinds
