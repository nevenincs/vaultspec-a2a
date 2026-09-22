"""Project confinement at the ACP permission rung.

A run is bound to one project. These tests drive the production permission
handler with the payload shapes the installed backends actually emit, and prove
two things the handler previously did not do: it refuses a tool call whose
arguments name a project other than the run's, and under autonomy it refuses a
call for a tool the run never declared instead of approving the first offered
option.

Real objects throughout: the frozen ``AcpModelConfig``, the real
``on_request_permission``, real directories on disk for the two projects, and
the subprocess-backed session context fixture.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from ...control.config import settings
from .. import _acp_rpc_handlers
from .._acp_rpc_handlers import (
    on_fs_read_text_file,
    on_fs_write_text_file,
    on_request_permission,
)
from .._acp_types import AcpModelConfig, AcpSessionContext, PermissionCallback
from .._json_contract import JsonObject, JsonValue

# The read tools the harness registry declares for the search server, in the
# qualified spelling the composed allowlist carries.
_DECLARED_READS: list[str] = [
    "mcp__vaultspec-rag__search_vault",
    "mcp__vaultspec-rag__search_codebase",
    "mcp__vaultspec-rag__get_code_file",
]

# Verbs the same server MOUNTS but the registry does not declare. They are the
# reachability the autonomous allowlist exists to close: index rebuild and index
# clean, which mutate whichever project the call names.
_UNDECLARED_VERBS: list[str] = [
    "reindex_vault",
    "reindex_codebase",
    "reindex_all",
    "clean_all",
    "clean_documents",
    "get_index_status",
]

# Options as claude-agent-acp 0.19.2 offers them (dist/acp-agent.js, canUseTool).
_CLAUDE_OPTIONS: list[JsonObject] = [
    {"optionId": "allow_always", "name": "Always Allow", "kind": "allow_always"},
    {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
    {"optionId": "reject", "name": "Reject", "kind": "reject_once"},
]


def _config(
    *,
    workspace_root: str | None,
    acp_family: str = "claude",
    acp_backend: str | None = "claude_code",
    permission_callback: PermissionCallback | None = None,
) -> AcpModelConfig:
    """Build the frozen config a run of the given lane is served with."""
    return AcpModelConfig(
        agent_config=None,
        permission_callback=permission_callback,
        workspace_root=workspace_root,
        command=["claude-code-acp"],
        env_vars={},
        session_id=None,
        mcp_servers=[],
        use_exec=False,
        provider="anthropic",
        runtime_authority=None,
        acp_backend=acp_backend,
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
        allowed_tools=list(_DECLARED_READS),
        acp_family=acp_family,
    )


async def _decide(
    title: str,
    raw_input: JsonObject,
    config: AcpModelConfig,
    ctx: AcpSessionContext,
    options: list[JsonObject] | None = None,
) -> str:
    """Drive the production handler and return the option id it selected."""
    params: JsonObject = {
        "toolCall": {"toolCallId": "tc-1", "title": title, "rawInput": raw_input},
        "options": list[JsonValue](options if options is not None else _CLAUDE_OPTIONS),
    }
    response = await on_request_permission(1, params, ctx, config)
    result = response.get("result")
    assert isinstance(result, dict)
    outcome = result.get("outcome")
    assert isinstance(outcome, dict)
    option_id = outcome.get("optionId")
    assert isinstance(option_id, str)
    return option_id


@pytest.fixture
def two_projects(tmp_path: Path) -> tuple[Path, Path]:
    """Create two real, separate project directories on disk."""
    bound = tmp_path / "bound-project"
    other = tmp_path / "other-project"
    bound.mkdir()
    other.mkdir()
    (bound / "src").mkdir()
    (other / ".vault").mkdir()
    return bound, other


@pytest.mark.asyncio
async def test_a_search_naming_a_second_workspace_is_refused(
    two_projects: tuple[Path, Path], acp_session_context: AcpSessionContext
) -> None:
    """A declared read tool pointed at ANOTHER project is refused.

    The tool is one the run declared and would otherwise be approved, so what is
    refused here is the argument, not the tool: this is the argument-borne scope
    escape that no per-server trust assertion can express.
    """
    bound, other = two_projects
    config = _config(workspace_root=str(bound))

    decision = await _decide(
        "mcp__vaultspec-rag__search_codebase",
        {"query": "credential handling", "project_root": str(other)},
        config,
        acp_session_context,
    )

    assert decision == "reject"


@pytest.mark.asyncio
async def test_the_same_search_against_its_own_project_still_runs(
    two_projects: tuple[Path, Path], acp_session_context: AcpSessionContext
) -> None:
    """Grounding survives: the run may search the project it is bound to."""
    bound, _ = two_projects
    config = _config(workspace_root=str(bound))

    assert (
        await _decide(
            "mcp__vaultspec-rag__search_codebase",
            {"query": "credential handling", "project_root": str(bound)},
            config,
            acp_session_context,
        )
        == "allow"
    )
    assert (
        await _decide(
            "mcp__vaultspec-rag__search_codebase",
            {"query": "credential handling", "project_root": str(bound / "src")},
            config,
            acp_session_context,
        )
        == "allow"
    )
    assert (
        await _decide(
            "mcp__vaultspec-rag__search_vault",
            {"query": "grounding"},
            config,
            acp_session_context,
        )
        == "allow"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("spelling", ["as_is", "trailing_separator", "dot_segment"])
async def test_a_differently_spelled_bound_root_is_still_the_bound_root(
    two_projects: tuple[Path, Path],
    acp_session_context: AcpSessionContext,
    spelling: str,
) -> None:
    """Several spellings of the run's own project reduce to one authority.

    The spellings that reached the four authorities in production differ this
    way, so a comparison that treated them as distinct projects would refuse the
    run's own grounding.
    """
    bound, _ = two_projects
    named = {
        "as_is": str(bound),
        "trailing_separator": str(bound) + "/",
        "dot_segment": str(bound / "src" / ".." / "src"),
    }[spelling]
    config = _config(workspace_root=str(bound))

    decision = await _decide(
        "mcp__vaultspec-rag__search_codebase",
        {"query": "x", "project_root": named},
        config,
        acp_session_context,
    )

    assert decision == "allow"


@pytest.mark.asyncio
async def test_a_recased_root_follows_the_filesystem_it_names(
    two_projects: tuple[Path, Path], acp_session_context: AcpSessionContext
) -> None:
    """A re-cased root is the same project exactly where the filesystem says so.

    The expectation is probed from the running filesystem rather than assumed:
    on a case-insensitive filesystem the upper-cased path IS the bound project
    and refusing it would refuse the run's own grounding, while on a
    case-sensitive one it names a directory that is not the bound project and
    admitting it would be the escape.
    """
    bound, _ = two_projects
    recased = Path(str(bound).upper())
    names_the_same_directory = (recased / "SRC").is_dir()
    config = _config(workspace_root=str(bound))

    decision = await _decide(
        "mcp__vaultspec-rag__search_codebase",
        {"query": "x", "project_root": str(recased)},
        config,
        acp_session_context,
    )

    assert decision == ("allow" if names_the_same_directory else "reject")


@pytest.mark.asyncio
async def test_the_parent_of_the_bound_project_is_not_the_bound_project(
    two_projects: tuple[Path, Path], acp_session_context: AcpSessionContext
) -> None:
    """Widening the root upward reaches the sibling project and is refused."""
    bound, _ = two_projects
    config = _config(workspace_root=str(bound))

    decision = await _decide(
        "mcp__vaultspec-rag__search_codebase",
        {"query": "x", "project_root": str(bound.parent)},
        config,
        acp_session_context,
    )

    assert decision == "reject"


@pytest.mark.asyncio
async def test_a_cross_project_read_is_refused_before_the_human_rung(
    two_projects: tuple[Path, Path], acp_session_context: AcpSessionContext
) -> None:
    """A supervised run cannot approve its way out of its bound project.

    The human at the permission rung is an authority over what the run may do
    inside its scope, not over what its scope is, so the refusal precedes the
    callback and the callback is never consulted.
    """
    bound, other = two_projects
    consulted: list[str] = []

    async def callback(name: str, _args: JsonObject, _options: list[JsonObject]) -> str:
        consulted.append(name)
        return "allow"

    config = _config(workspace_root=str(bound), permission_callback=callback)

    decision = await _decide(
        "mcp__vaultspec-rag__get_code_file",
        {"path": "src/secret.py", "project_root": str(other)},
        config,
        acp_session_context,
    )

    assert decision == "reject"
    assert consulted == []


@pytest.mark.asyncio
async def test_a_run_with_no_bound_project_may_name_no_project(
    two_projects: tuple[Path, Path], acp_session_context: AcpSessionContext
) -> None:
    """No authority to compare against is not permission to proceed."""
    _, other = two_projects
    config = _config(workspace_root=None)

    decision = await _decide(
        "mcp__vaultspec-rag__search_codebase",
        {"query": "x", "project_root": str(other)},
        config,
        acp_session_context,
    )

    assert decision == "reject"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["project_root", "projectRoot", "workspace_root"])
async def test_a_nested_or_recased_project_argument_is_still_seen(
    two_projects: tuple[Path, Path],
    acp_session_context: AcpSessionContext,
    key: str,
) -> None:
    """The argument scan is not a top-level key lookup on one spelling."""
    bound, other = two_projects
    config = _config(workspace_root=str(bound))

    decision = await _decide(
        "mcp__vaultspec-rag__search_codebase",
        {"query": "x", "options": {"scope": {key: str(other)}}},
        config,
        acp_session_context,
    )

    assert decision == "reject"


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", _UNDECLARED_VERBS)
async def test_an_undeclared_server_verb_is_refused_under_autonomy(
    two_projects: tuple[Path, Path],
    acp_session_context: AcpSessionContext,
    verb: str,
) -> None:
    """A verb the server mounts but the registry never declared is refused.

    These reach the permission rung precisely BECAUSE they are undeclared - the
    CLI's static pre-approval covers only the declared reads - and the branch
    that used to receive them approved the first offered option unconditionally.
    """
    bound, _ = two_projects
    config = _config(workspace_root=str(bound))

    decision = await _decide(
        f"mcp__vaultspec-rag__{verb}",
        {"project_root": str(bound)},
        config,
        acp_session_context,
    )

    assert decision == "reject"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "title",
    [
        "Write C:\\project\\src\\app.py",
        "Edit C:\\project\\src\\app.py",
        "git push --force origin main",
        "Read the plan and rewrite the failing module",
        "Find `C:\\project` `**/*.py`",
    ],
)
async def test_an_uncovered_claude_call_is_refused_not_blanket_approved(
    two_projects: tuple[Path, Path],
    acp_session_context: AcpSessionContext,
    title: str,
) -> None:
    """The titles claude-agent-acp emits for uncovered calls are all refused.

    ``Write``/``Edit`` are the mutating built-ins, the bare command line is a
    ``Bash`` call, and the fourth is a ``Task`` whose DESCRIPTION begins with an
    allowlisted tool name - the case that a leading-word match would have
    approved. The last is the adapter's ``Glob`` label, which carries no tool
    name at all and so cannot be allowlisted by name.
    """
    bound, _ = two_projects
    config = _config(workspace_root=str(bound))

    decision = await _decide(title, {}, config, acp_session_context)

    assert decision == "reject"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob"])
async def test_the_claude_native_read_floor_stays_reachable(
    two_projects: tuple[Path, Path],
    acp_session_context: AcpSessionContext,
    tool: str,
) -> None:
    """The lane's own read tools remain approved when named exactly."""
    bound, _ = two_projects
    config = _config(workspace_root=str(bound))

    assert await _decide(tool, {}, config, acp_session_context) == "allow"


@pytest.mark.asyncio
async def test_the_kimi_lane_keeps_its_proven_behaviour(
    two_projects: tuple[Path, Path], acp_session_context: AcpSessionContext
) -> None:
    """Generalising the allowlist did not change the lane it was proven on."""
    bound, other = two_projects
    kimi_options: list[JsonObject] = [
        {"optionId": "approve", "kind": "allow_once"},
        {"optionId": "approve_for_session", "kind": "allow_always"},
        {"optionId": "reject", "kind": "reject_once"},
    ]
    config = _config(
        workspace_root=str(bound), acp_family="kimi", acp_backend="kimi_cli"
    )

    assert (
        await _decide(
            "ReadFile: src/a.py", {}, config, acp_session_context, kimi_options
        )
        == "approve"
    )
    assert (
        await _decide(
            "WriteFile: src/a.py", {}, config, acp_session_context, kimi_options
        )
        == "reject"
    )
    assert (
        await _decide(
            "search_codebase: x",
            {"project_root": str(other)},
            config,
            acp_session_context,
            kimi_options,
        )
        == "reject"
    )


@pytest.mark.asyncio
async def test_privileged_callback_refuses_static_symlink_escape(
    two_projects: tuple[Path, Path],
    acp_session_context: AcpSessionContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound, protected = two_projects
    secret = protected / "service.token"
    secret.write_text("must-not-leak", encoding="utf-8")
    escape = bound / "escape"
    escape.symlink_to(protected, target_is_directory=True)
    monkeypatch.setattr(settings, "provider_identity_launcher", Path("/configured"))

    response = await on_fs_read_text_file(
        1,
        {"path": "escape/service.token"},
        acp_session_context,
        _config(workspace_root=str(bound)),
    )

    assert "error" in response
    assert "must-not-leak" not in str(response)


@pytest.mark.skipif(sys.platform == "win32", reason="Linux descriptor contract")
@pytest.mark.asyncio
async def test_privileged_callback_refuses_replaced_workspace_root(
    two_projects: tuple[Path, Path],
    acp_session_context: AcpSessionContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound, protected = two_projects
    managed = bound.parent / "managed"
    managed.mkdir()
    admitted = managed / "project"
    admitted.symlink_to(protected, target_is_directory=True)
    secret = protected / "service.token"
    secret.write_text("must-not-leak", encoding="utf-8")
    monkeypatch.setattr(settings, "provider_identity_launcher", Path("/configured"))
    monkeypatch.setattr(settings, "workspace_root", managed)

    response = await on_fs_read_text_file(
        1,
        {"path": "service.token"},
        acp_session_context,
        _config(workspace_root=str(admitted)),
    )

    assert "error" in response
    assert "must-not-leak" not in str(response)


@pytest.mark.skipif(sys.platform == "win32", reason="Linux descriptor contract")
@pytest.mark.asyncio
async def test_privileged_read_stays_on_opened_parent_during_symlink_swap(
    two_projects: tuple[Path, Path],
    acp_session_context: AcpSessionContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound, protected = two_projects
    safe = bound / "safe"
    parked = bound / "parked"
    safe.mkdir()
    (safe / "data.txt").write_text("workspace-data", encoding="utf-8")
    (protected / "data.txt").write_text("service-secret", encoding="utf-8")
    monkeypatch.setattr(settings, "provider_identity_launcher", Path("/configured"))
    real_open = os.open
    swapped = False

    def swapping_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "data.txt" and dir_fd is not None and not swapped:
            swapped = True
            safe.rename(parked)
            safe.symlink_to(protected, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(_acp_rpc_handlers.os, "open", swapping_open)
    response = await on_fs_read_text_file(
        1,
        {"path": "safe/data.txt"},
        acp_session_context,
        _config(workspace_root=str(bound)),
    )

    assert response["result"] == {"content": "workspace-data"}
    assert "service-secret" not in str(response)


@pytest.mark.skipif(sys.platform == "win32", reason="Linux descriptor contract")
@pytest.mark.asyncio
async def test_privileged_write_stays_on_opened_parent_during_symlink_swap(
    two_projects: tuple[Path, Path],
    acp_session_context: AcpSessionContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound, protected = two_projects
    safe = bound / "safe"
    parked = bound / "parked"
    safe.mkdir()
    protected_target = protected / "target.txt"
    protected_target.write_text("service-state", encoding="utf-8")
    monkeypatch.setattr(settings, "provider_identity_launcher", Path("/configured"))
    # The privileged write re-groups the file to the agent GID; an unprivileged
    # test process can only fchown to a group it belongs to.
    assert os.name == "posix"
    monkeypatch.setattr(settings, "provider_agent_gid", os.getgid())
    real_open = os.open
    swapped = False

    def swapping_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "target.txt" and dir_fd is not None and not swapped:
            swapped = True
            safe.rename(parked)
            safe.symlink_to(protected, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(_acp_rpc_handlers.os, "open", swapping_open)
    response = await on_fs_write_text_file(
        1,
        {"path": "safe/target.txt", "content": "workspace-write"},
        acp_session_context,
        _config(workspace_root=str(bound)),
    )

    assert response["result"] == {}
    assert protected_target.read_text(encoding="utf-8") == "service-state"
    assert (parked / "target.txt").read_text(encoding="utf-8") == "workspace-write"
