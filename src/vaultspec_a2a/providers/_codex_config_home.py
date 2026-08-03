"""Per-run isolated CODEX_HOME carrying the declared read-only MCP servers.

Codex resolves its MCP servers and approval/sandbox config from ``CODEX_HOME``
(default ``~/.codex``); left on the operator's home, a worker inherits every
ambient ``[mcp_servers.*]`` block the operator has (e.g. ``node_repl``,
``computer-use``), violating the harness invariant that the agent's MCP surface
be exactly the declared set. (The Claude/Z.ai ACP lane enforces the same
invariant differently: it runs in the operator's real config home and confines
the surface via run-workspace projections, per the no-auth
ambient-environment contract.)

This module builds a per-run, worker-owned ``CODEX_HOME`` whose ``config.toml``
carries EXACTLY the declared read-only harness servers as ``[mcp_servers.<name>]``
blocks. Codex auth is file-based (``auth.json``), so the base home's
``auth.json`` is copied in to preserve authentication; nothing else is carried,
so the operator's ambient MCP config is suppressed.

One registry (``_KNOWN_MCP_SERVERS``), two serializations: this is the Codex
transport for the same read-only servers the Claude lane projects. Root
resolution and the orphan-home sweep live in ``_config_home_roots``: on an
armed desktop install the Codex home is created inside the accounted
application-state root, and a crashed run's home is reclaimed by the age-gated
sweep, scoped to this module's own prefix so it never collects a directory
belonging to another product.

The same ``config.toml`` also carries the run's web-grounding posture. Codex
does not expose web search as an allowlistable tool name the way the Claude
lane's built-ins are named; it is a configuration mode, so this file is the
whole delivery seam for the capability on this lane. The mode is ALWAYS written
explicitly - omitting it is not a safe default, because Codex enables web search
by default (its own deprecation notice for the superseded ``[features]`` keys
says so in as many words), so a home that stayed silent would ship an outward
reach nothing admitted.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from ..utils.enums import CodexWebSearchMode
from ._config_home_roots import sweep_orphan_homes, temp_home_root

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ._json_contract import JsonObject

__all__ = [
    "SERVED_WEB_SEARCH_MODE",
    "build_codex_config_home",
    "cleanup_codex_config_home",
    "render_codex_config_toml",
    "resolve_codex_web_search_mode",
    "sweep_orphan_codex_homes",
]

_OVERRIDE_PROVIDER = "vaultspec-override"
_HOME_PREFIX = "vaultspec-codex-home-"

logger = logging.getLogger(__name__)

# TOML bare-key charset; a server name outside it is quoted in the table header.
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_str(value: str) -> str:
    """Return a TOML basic string via ``json.dumps``.

    TOML basic strings and JSON strings share the same double-quote delimiter and
    the same backslash escapes for ``"``, ``\\``, and the C0 controls these values
    can contain (tab/newline), so ``json.dumps`` output is a valid TOML basic
    string for the registry-controlled ASCII values here (server names, uvx args,
    tool names). It is NOT a general TOML serializer - it holds because the inputs
    are constrained; every emitted document is asserted parseable via ``tomllib``
    in the tests as the backstop.
    """
    return json.dumps(value)


def _toml_str_array(values: Sequence[str]) -> str:
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


def _table_key(name: str) -> str:
    return name if _BARE_KEY.match(name) else _toml_str(name)


def _required_server_string(spec: JsonObject, field: str, *, server: str) -> str:
    """Read one required non-blank string from a declared MCP server spec."""
    value = spec.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Codex MCP server {server!r} field {field!r} must be a non-blank string"
        )
    return value


def _optional_server_string_list(
    spec: JsonObject, field: str, *, server: str
) -> list[str]:
    """Read one optional string-list field without widening the wire contract."""
    if field not in spec:
        return []
    value = spec[field]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(
            f"Codex MCP server {server!r} field {field!r} must be a list of strings"
        )
    return [item for item in value if isinstance(item, str)]


def _optional_server_environment(spec: JsonObject, *, server: str) -> dict[str, str]:
    """Read one optional string environment object from a server spec."""
    if "env" not in spec:
        return {}
    value = spec["env"]
    if not isinstance(value, dict):
        raise ValueError(f"Codex MCP server {server!r} field 'env' must be an object")
    environment: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str):
            raise ValueError(
                f"Codex MCP server {server!r} field 'env' must be an object of strings"
            )
        environment[key] = item
    return environment


# The served posture for a lane that carries web proof. Cached is the safer mode
# and costs no egress, but a lane answering from a provider-maintained index
# while its siblings read the live web makes a multi-provider graph's findings
# differ by provider rather than by evidence. Parity of reach is the property
# this capability exists to establish, so live is what a proven lane serves.
SERVED_WEB_SEARCH_MODE = CodexWebSearchMode.LIVE


def resolve_codex_web_search_mode(
    *, web_proven: bool, configured: CodexWebSearchMode | None = None
) -> CodexWebSearchMode:
    """Return the ``web_search`` mode a run may emit.

    Two inputs, deliberately asymmetric. *web_proven* is the lane-admission
    verdict - whether a live test has proven a completed retrieval on the Codex
    lane - and it is ABSOLUTE: an unproven lane resolves to
    :attr:`~CodexWebSearchMode.DISABLED` no matter what a deployment configured,
    so no configuration can talk a lane past a proof it does not have.
    *configured* is the deployment's preference and applies only above that gate,
    which is what keeps :attr:`~CodexWebSearchMode.CACHED` selectable for an
    install that wants search with zero egress; left unset, a proven lane serves
    :data:`SERVED_WEB_SEARCH_MODE`.

    The verdict arrives as a parameter rather than being read here on purpose:
    lane admission is one declaration owned by one module, and a second reader
    that could disagree with it is the failure this argument shape prevents.
    """
    if not web_proven:
        return CodexWebSearchMode.DISABLED
    return configured if configured is not None else SERVED_WEB_SEARCH_MODE


def _restrict(path: Path) -> None:
    """Best-effort owner-only permissions on a path; never raises.

    POSIX-effective (0o700 for the dir, applied to the credential copy too);
    a no-op on Windows, where the per-user temp tree is already ACL-scoped.
    """
    with suppress(OSError):
        path.chmod(0o700 if path.is_dir() else 0o600)


def render_codex_config_toml(
    specs: Sequence[JsonObject],
    *,
    web_search: CodexWebSearchMode,
    base_url_override: str | None = None,
) -> str:
    """Render the ``config.toml`` body for the declared read-only servers.

    Emits one ``[mcp_servers.<name>]`` block per spec with ``command`` and
    ``args``, plus an ``[mcp_servers.<name>.env]`` sub-table when the spec carries
    env. The read-verb constraint names the server's read ``tools`` in
    ``enabled_tools`` (an exact allowlist, so no write verb the server also exposes
    can be invoked) and sets ``default_tools_approval_mode = "auto"`` so those
    reads run without a prompt under the headless ``approval_policy = "never"``
    plus ``sandbox = "read-only"`` composition. Deterministic and stdlib-
    ``tomllib``-parseable.

    *web_search* is written unconditionally, and FIRST. Unconditionally because
    Codex enables web search when the key is absent, so silence is a posture, not
    an abstention; first because TOML binds a bare key to the table above it - the
    same line emitted after ``[mcp_servers.<name>]`` would become an unrecognised
    option of that server rather than the run's web posture.

    It is REQUIRED and has no default, matching the registry's trust axes
    (``_acp_mcp``): unsafe-by-omission, never silently permissive. A default would
    be worse than inconvenient here - while the proven-lane set is empty every
    resolution yields ``disabled``, so a defaulted argument would render the gate
    binding invisible, and deleting the binding would leave every test green. A
    caller that has not decided the posture must fail to build, not build quietly.

    *base_url_override*, when set, names a ``[model_providers.*]`` table and
    selects it, redirecting the lane's API traffic at that endpoint. See
    :func:`build_codex_config_home` for why the seam exists and why it stays
    absent by default.
    """
    # Kept ahead of every table header; see the docstring for why this is a
    # correctness constraint rather than a layout preference.
    blocks: list[str] = [f"web_search = {_toml_str(web_search.value)}"]
    if base_url_override:
        # Same bare-key-before-tables constraint as web_search above.
        blocks.append(
            f"model_provider = {_toml_str(_OVERRIDE_PROVIDER)}\n\n"
            f"[model_providers.{_OVERRIDE_PROVIDER}]\n"
            f"name = {_toml_str(_OVERRIDE_PROVIDER)}\n"
            f"base_url = {_toml_str(base_url_override)}\n"
            'wire_api = "chat"'
        )
    for spec in specs:
        name = _required_server_string(spec, "name", server="<unnamed>")
        command = _required_server_string(spec, "command", server=name)
        args = _optional_server_string_list(spec, "args", server=name)
        tools = _optional_server_string_list(spec, "tools", server=name)
        environment = _optional_server_environment(spec, server=name)
        key = _table_key(name)
        lines = [f"[mcp_servers.{key}]", f"command = {_toml_str(command)}"]
        lines.append(f"args = {_toml_str_array(args)}")
        # Read-verb allowlist: exactly the registry's read tools, auto-approved.
        lines.append(f"enabled_tools = {_toml_str_array(tools)}")
        lines.append('default_tools_approval_mode = "auto"')
        block = "\n".join(lines)
        if environment:
            env_lines = [f"[mcp_servers.{key}.env]"]
            env_lines += [
                f"{_table_key(key)} = {_toml_str(value)}"
                for key, value in environment.items()
            ]
            block = block + "\n\n" + "\n".join(env_lines)
        blocks.append(block)
    return "\n\n".join(blocks) + "\n"


def build_codex_config_home(
    specs: Sequence[JsonObject],
    base_home: Path | None,
    *,
    web_search: CodexWebSearchMode,
    base_url_override: str | None = None,
) -> Path:
    """Create a per-run ``CODEX_HOME`` carrying only the declared servers.

    Copies ``auth.json`` from *base_home* (if present) to preserve Codex's
    file-based auth, then writes a ``config.toml`` with exactly the declared
    ``[mcp_servers.<name>]`` blocks. The caller sets ``CODEX_HOME`` to the
    returned path and MUST call :func:`cleanup_codex_config_home` after reap.

    Created inside the armed desktop profile's temporary-home root when one is
    declared (else the system temp directory), mirroring the Claude isolated
    config home so an uninstall can account for it and a system-wide temp sweep
    cannot delete it out from under a live run.

    *web_search* is the run's web posture and is required - see
    :func:`render_codex_config_toml` for why it carries no default. Production
    always passes the output of :func:`resolve_codex_web_search_mode`.

    *base_url_override* redirects the lane at a caller-named endpoint. It is
    absent by default and must stay that way: this home exists precisely so a run
    cannot inherit ambient configuration, and an override is a hole in that
    property rather than a feature of it. It exists because the failure direction
    of a provider lane is otherwise unobservable from outside the system - the
    admitted lane succeeds on every input the gateway accepts - and a condition
    taxonomy that can never be exercised against a real refusal is a claim rather
    than a proof. The sibling ACP lane already accepts the same redirect through
    its own base-URL variable, so this closes an asymmetry rather than opening a
    new class of control.
    """
    # mkdtemp creates an owner-only (0700) directory, so the copied credential is
    # traversal-protected by the dir even before the file's own mode is set.
    home = Path(tempfile.mkdtemp(prefix=_HOME_PREFIX, dir=temp_home_root()))
    # Reclaim what earlier crashed runs left behind, once per home creation -
    # mirrors the Claude call site: there is no supervisor to run this sweep on
    # a schedule, so it piggybacks on every creation instead.
    with suppress(OSError):
        sweep_orphan_codex_homes(keep=home)
    try:
        _restrict(home)
        if base_home is not None:
            auth = base_home / "auth.json"
            if auth.exists():
                dest = home / "auth.json"
                shutil.copy2(auth, dest)
                # Defensive: pin the credential copy to owner-only regardless of
                # the source's mode (POSIX-effective; a no-op on Windows, where
                # the temp tree is already user-scoped).
                _restrict(dest)
        (home / "config.toml").write_text(
            render_codex_config_toml(
                specs,
                web_search=web_search,
                base_url_override=base_url_override,
            ),
            encoding="utf-8",
        )
    except BaseException:
        # A mid-build failure (e.g. copy error) must not leak the dir with a
        # partial credential copy; remove it before re-raising.
        cleanup_codex_config_home(home)
        raise
    logger.debug(
        "Codex isolated config home created at %s (%d server(s), web_search=%s)",
        home,
        len(specs),
        web_search.value,
    )
    return home


def cleanup_codex_config_home(home: Path | None) -> None:
    """Best-effort removal of a per-run Codex config home; never raises."""
    if home is None:
        return
    shutil.rmtree(home, ignore_errors=True)


def sweep_orphan_codex_homes(
    *, keep: Path | None = None, root: Path | None = None
) -> list[Path]:
    """Remove per-run Codex config homes abandoned by a crashed run.

    A thin, prefix-bound wrapper over the shared
    :func:`~._config_home_roots.sweep_orphan_homes` core, mirroring the Claude
    side's ``sweep_orphan_config_homes`` - partial application to this module's
    own ``_HOME_PREFIX``, not a re-export shim. The age-gating and
    root-resolution rationale lives once, in the shared core.

    Args:
        keep: A home to leave alone regardless of age - the caller's own.
        root: Directory to sweep; defaults to the profile's temporary-home root.

    Returns:
        The homes removed, for the caller to log.
    """
    return sweep_orphan_homes(prefix=_HOME_PREFIX, keep=keep, root=root)
