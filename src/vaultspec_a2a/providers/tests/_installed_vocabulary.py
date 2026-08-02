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

import json
import re
import shutil
import subprocess
from pathlib import Path

__all__ = [
    "MissingInstalledVocabularyError",
    "acp_adapter_error_kinds",
    "acp_error_kinds",
    "acp_sdk_types_path",
    "codex_error_info_variants",
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


def _acp_adapter_bundle_path() -> Path:
    """Return the installed ACP adapter bundle that attaches the error kind."""
    return (
        _repo_root()
        / "node_modules"
        / "@agentclientprotocol"
        / "claude-agent-acp"
        / "dist"
        / "acp-agent.js"
    )


_ACP_ADAPTER_OWN_KIND = re.compile(r"""errorKindData\(\s*["']([a-z0-9_]+)["']""")


def acp_adapter_error_kinds() -> frozenset[str]:
    """Return the error kinds the ACP adapter raises on its OWN behalf.

    The adapter mostly forwards the agent SDK's kind, but it also mints kinds of
    its own for failures the SDK never sees - a turn that ends producing
    nothing, for instance. Those reach the same wire field and are NOT members
    of the SDK union, so a mapping built from the union alone would let them
    fall through. Only literal arguments are recovered here; the forwarding call
    sites pass a variable and are covered by the SDK union instead.
    """
    bundle = _acp_adapter_bundle_path()
    try:
        source = bundle.read_text(encoding="utf-8")
    except OSError as exc:
        raise MissingInstalledVocabularyError(
            "the installed @agentclientprotocol/claude-agent-acp bundle is "
            f"unavailable at {bundle} (run the project's npm install)"
        ) from exc
    return frozenset(_ACP_ADAPTER_OWN_KIND.findall(source))


def codex_error_info_variants(destination: Path) -> frozenset[str]:
    """Return the Codex error-info variants the INSTALLED app-server declares.

    Generated from the binary on the spot rather than read from a committed
    copy: a checked-in schema records what the protocol looked like when someone
    last refreshed it, which is the drift this reader exists to detect. The
    generation writes into *destination*, which the caller owns.

    Both shapes the discriminator takes are returned in one set - the bare
    categorical strings and the keys of the single-key object variants - because
    the mapping treats them as one vocabulary.
    """
    executable = shutil.which("codex")
    if executable is None:
        raise MissingInstalledVocabularyError(
            "the codex CLI is not on PATH, so the app-server protocol schema "
            "cannot be generated from the installed binary"
        )
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [executable, "app-server", "generate-json-schema", "--out", str(destination)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        raise MissingInstalledVocabularyError(
            "the installed codex CLI could not generate its protocol schema "
            f"(exit {completed.returncode}): {completed.stderr.strip()[:400]}"
        )

    schema_path = destination / "codex_app_server_protocol.v2.schemas.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MissingInstalledVocabularyError(
            f"the generated codex protocol schema is unreadable at {schema_path}"
        ) from exc

    definitions = schema.get("definitions")
    error_info = definitions.get("CodexErrorInfo") if definitions else None
    branches = error_info.get("oneOf") if isinstance(error_info, dict) else None
    if not isinstance(branches, list) or not branches:
        raise MissingInstalledVocabularyError(
            "the generated codex protocol schema no longer declares CodexErrorInfo "
            f"as a union in {schema_path}; the error vocabulary moved"
        )

    variants: set[str] = set()
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        if branch.get("type") == "string":
            members = branch.get("enum")
            if isinstance(members, list):
                variants.update(m for m in members if isinstance(m, str))
        elif branch.get("type") == "object":
            required = branch.get("required")
            if isinstance(required, list):
                variants.update(name for name in required if isinstance(name, str))
    if not variants:
        raise MissingInstalledVocabularyError(
            f"the generated CodexErrorInfo union lists no variants in {schema_path}"
        )
    return frozenset(variants)
