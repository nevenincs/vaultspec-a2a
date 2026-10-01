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
import subprocess
from pathlib import Path
from typing import cast

from ...graph.enums import Provider
from ..cli_resolution import resolve_provider_cli_executable

__all__ = [
    "MissingInstalledVocabularyError",
    "acp_adapter_error_kinds",
    "acp_adapter_failure_categories",
    "acp_adapter_permission_mode_ids",
    "acp_adapter_session_mode_source",
    "acp_adapter_shell_tool_names",
    "acp_adapter_source",
    "acp_error_kinds",
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


def _acp_adapter_dist() -> Path:
    """Return the installed ACP adapter's compiled module directory."""
    return (
        _repo_root()
        / "node_modules"
        / "@agentclientprotocol"
        / "claude-agent-acp"
        / "dist"
    )


def _acp_adapter_bundle_path() -> Path:
    """Return the installed ACP adapter bundle that attaches the error kind."""
    return _acp_adapter_dist() / "acp-agent.js"


def _acp_adapter_module_source(module: str) -> str:
    """Return one compiled adapter module's source text.

    The adapter is no longer a single bundle: the session surfaces this project
    pins against are split across modules, and which module owns a surface is
    itself a fact about the installed artefact. Naming the module at the call
    site keeps that fact visible instead of hiding it behind a reader that
    searches the whole tree and would quietly match a renamed neighbour.
    """
    path = _acp_adapter_dist() / module
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MissingInstalledVocabularyError(
            "the installed @agentclientprotocol/claude-agent-acp bundle is "
            f"unavailable at {path} (run the project's npm install)"
        ) from exc


def acp_adapter_source() -> str:
    """Return the installed ACP adapter bundle's source text.

    The adapter decides what a session's options mean - which of them the
    caller may override and which it reassigns afterwards - so a client that
    pins a posture through those options is making a claim about THIS bundle.
    Handing the source to the caller lets that claim be checked against the
    artefact that will run rather than against a reading of it.
    """
    bundle = _acp_adapter_bundle_path()
    try:
        return bundle.read_text(encoding="utf-8")
    except OSError as exc:
        raise MissingInstalledVocabularyError(
            "the installed @agentclientprotocol/claude-agent-acp bundle is "
            f"unavailable at {bundle} (run the project's npm install)"
        ) from exc


#: The adapter module that owns the session permission-mode catalog.
_ACP_SESSION_MODE_MODULE = "session-mode.js"

_ACP_AVAILABLE_MODES = re.compile(
    r"buildAvailableModes\([^)]*\)\s*\{(.*?)\n    \}", re.DOTALL
)
_ACP_MODE_ID = re.compile(r"""id:\s*["']([A-Za-z]+)["']""")


def acp_adapter_session_mode_source() -> str:
    """Return the installed adapter module that owns the mode catalog.

    The catalog left the single bundle and now lives in its own module, so a
    claim about which modes a session can run in is a claim about THIS file.
    Handing it to the caller keeps the claim checkable against the artefact
    that will run.
    """
    return _acp_adapter_module_source(_ACP_SESSION_MODE_MODULE)


def acp_adapter_permission_mode_ids() -> frozenset[str]:
    """Return the permission-mode ids the installed ACP adapter can advertise.

    A mode id is a wire value the adapter validates against its own list, so a
    client asking for one is asking for a member of THAT list. Parsed from the
    builder rather than restated, so a renamed or withdrawn mode surfaces here
    instead of at the first unattended run.

    Only the ADVERTISED ids are returned. The adapter still parses a wider set
    of mode names than it offers, and a name it parses but never advertises is
    refused when a client asks for it, so the parser's list would overstate
    what a session can actually be pinned to.
    """
    builder = _ACP_AVAILABLE_MODES.search(acp_adapter_session_mode_source())
    if builder is None:
        raise MissingInstalledVocabularyError(
            "the installed ACP adapter no longer builds its available modes in "
            f"{_acp_adapter_dist() / _ACP_SESSION_MODE_MODULE}; the "
            "permission-mode vocabulary moved"
        )
    ids = frozenset(_ACP_MODE_ID.findall(builder.group(1)))
    if not ids:
        raise MissingInstalledVocabularyError(
            "the installed ACP adapter's mode builder lists no mode ids in "
            f"{_acp_adapter_dist() / _ACP_SESSION_MODE_MODULE}"
        )
    return ids


#: The adapter module that binds each tool name to the reporter that renders it.
_ACP_REPORTER_MODULE = "tool-calls/reporters/index.js"

_ACP_REPORTER_TABLE = re.compile(r"const reporters = \{(.*?)\n\};", re.DOTALL)
_ACP_SHELL_REPORTER = re.compile(r"(\w+):\s*bash,")


def acp_adapter_shell_tool_names() -> frozenset[str]:
    """Return the tool names the installed adapter renders as shell commands.

    The adapter binds one reporter per tool it knows, and the shell reporter is
    shared by every tool whose call IS a command line. That binding is the
    adapter's own answer to "which of the CLI's built-ins execute commands",
    which is the question a terminal-less persona's deny list has to answer the
    same way. Reading it is how a newly exposed shell tool shows up as a gap in
    the deny list rather than as a command a denied persona can still run.
    """
    table = _ACP_REPORTER_TABLE.search(_acp_adapter_module_source(_ACP_REPORTER_MODULE))
    if table is None:
        raise MissingInstalledVocabularyError(
            "the installed ACP adapter no longer binds tool reporters in "
            f"{_acp_adapter_dist() / _ACP_REPORTER_MODULE}; the shell-tool "
            "vocabulary moved"
        )
    names = frozenset(_ACP_SHELL_REPORTER.findall(table.group(1)))
    if not names:
        raise MissingInstalledVocabularyError(
            "the installed ACP adapter's reporter table binds no tool to its "
            f"shell reporter in {_acp_adapter_dist() / _ACP_REPORTER_MODULE}"
        )
    return names


#: The adapter module that classifies a provider failure kind.
_ACP_FAILURE_MODULE = "session-failure-extension.js"

_ACP_FAILURE_SWITCH = re.compile(
    r"function providerFailureCategory\([^)]*\)\s*\{(.*?)\n\}", re.DOTALL
)
_ACP_FAILURE_GROUP = re.compile(
    r"((?:\s*case\s+(?:\"[a-z0-9_]+\"|undefined):)+)\s*\n\s*return \"([a-z_]+)\";"
)
_ACP_FAILURE_CASE = re.compile(r"""case\s+"([a-z0-9_]+)":""")


def acp_adapter_failure_categories() -> dict[str, str]:
    """Return the failure category the installed adapter assigns each error kind.

    The adapter classifies every kind it forwards - which remedy the failure
    calls for, in its own words - and that classification ships in the artefact
    that runs. Reading it is what lets this project's own condition mapping be
    checked against the adapter's judgement instead of against a reading of the
    kind's NAME, which is all a hand-maintained table ever has.

    The adapter's own floor category is included rather than filtered, because
    "the adapter could not classify this either" is the one answer that
    justifies this project resolving a kind to its own floor, and a reader that
    dropped it would leave the caller unable to tell that case from an absent
    one.
    """
    body = _ACP_FAILURE_SWITCH.search(_acp_adapter_module_source(_ACP_FAILURE_MODULE))
    if body is None:
        raise MissingInstalledVocabularyError(
            "the installed ACP adapter no longer classifies provider failures in "
            f"{_acp_adapter_dist() / _ACP_FAILURE_MODULE}; the category "
            "vocabulary moved"
        )
    categories = {
        kind: category
        for cases, category in _ACP_FAILURE_GROUP.findall(body.group(1))
        for kind in _ACP_FAILURE_CASE.findall(cases)
    }
    if not categories:
        raise MissingInstalledVocabularyError(
            "the installed ACP adapter's failure classifier lists no error kinds "
            f"in {_acp_adapter_dist() / _ACP_FAILURE_MODULE}"
        )
    return categories


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


def _codex_error_branch_names(raw_branch: object) -> set[str]:
    """Read string or single-key object variants from one schema branch."""
    if not isinstance(raw_branch, dict):
        return set()
    branch = cast("dict[str, object]", raw_branch)
    branch_type = branch.get("type")
    key = "enum" if branch_type == "string" else "required"
    if branch_type not in {"string", "object"}:
        return set()
    members = branch.get(key)
    if not isinstance(members, list):
        return set()
    return {
        member for member in cast("list[object]", members) if isinstance(member, str)
    }


def _parse_codex_error_info_variants(schema_path: Path) -> frozenset[str]:
    try:
        raw_schema: object = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MissingInstalledVocabularyError(
            f"the generated codex protocol schema is unreadable at {schema_path}"
        ) from exc
    assert isinstance(raw_schema, dict)
    schema = cast("dict[str, object]", raw_schema)

    raw_definitions = schema.get("definitions")
    error_info: object = None
    if isinstance(raw_definitions, dict):
        definitions = cast("dict[str, object]", raw_definitions)
        error_info = definitions.get("CodexErrorInfo")
    branches: object = None
    if isinstance(error_info, dict):
        branches = cast("dict[str, object]", error_info).get("oneOf")
    if not isinstance(branches, list) or not branches:
        raise MissingInstalledVocabularyError(
            "the generated codex protocol schema no longer declares CodexErrorInfo "
            f"as a union in {schema_path}; the error vocabulary moved"
        )

    variants: set[str] = set()
    for raw_branch in cast("list[object]", branches):
        variants.update(_codex_error_branch_names(raw_branch))
    if not variants:
        raise MissingInstalledVocabularyError(
            f"the generated CodexErrorInfo union lists no variants in {schema_path}"
        )
    return frozenset(variants)


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
    executable = resolve_provider_cli_executable(Provider.CODEX)
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
    return _parse_codex_error_info_variants(schema_path)
