"""Live proof: the strict claude session mounts EXACTLY the injected MCP surface.

No mocks, no tape, no injected protocol. The model is built by the real
``ProviderFactory``, armed through the real ``with_mcp_servers`` seam, and
drives the real ``claude-agent-acp`` subprocess through REAL ``session/prompt``
turns on the operator's ambient login.

Two live proofs, each of which fails if its control is removed:

- **Surface bounding** (scratch workspace): the workspace is seeded with a live
  project-scope canary server (a real stdio MCP server, enabled for
  auto-approval by the workspace's own settings) and the operator's real
  user-global server names are read from the ambient CLI config. Without
  ``strictMcpConfig`` the CLI mounts both scopes - the pre-fix behaviour,
  observed live - so their absence from the model's own tool listing, beside
  the PRESENCE of the injected server, is the strict control working. The
  seeded workspace must come back byte-identical: surfacing writes nothing.

- **Completed real work** (this repository as the run workspace): the injected
  ``vaultspec-rag`` search tool is CALLED on a real turn over an indexed tree
  and must return content - the completed-turn standard; a mount or a connect
  log proves spawn, not grounding. The repository's own ``.mcp.json`` declares
  a WRITABLE vault MCP server among others, so this run doubles as the
  original write-leak regression: none of those project-scope names may join
  the surface.

Service-marked, so deselected from the default suite. Skips name exactly the
missing prerequisite; nothing is reported green for infrastructure absence.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from ...control.config import settings
from ...graph.enums import Model, Provider
from .._acp_mcp import harness_allowed_tool_names, resolve_harness_mcp_servers
from .._subprocess import kill_process_tree
from ..acp_chat_model import AcpChatModel
from ..factory import _CLAUDE_ACP_JS, ProviderFactory, _classify_acp_command

_RAG = "vaultspec-rag"
_CANARY = "leak-canary"
_REPO_ROOT = Path(__file__).resolve().parents[4]

# A real, instantly-serving stdio MCP server used as the project-scope canary.
# It must be genuinely mountable so that removing the strict control makes it
# (and the ambient user-global servers) join the surface.
_CANARY_SERVER = '''\
from mcp.server.mcpserver import MCPServer

server = MCPServer(name="leak-canary")


@server.tool()
def chirp() -> str:
    """Return the literal string chirp."""
    return "chirp"


if __name__ == "__main__":
    server.run("stdio")
'''


def _require_acp_entry() -> None:
    if settings.acp_backend != "binary" and not _CLAUDE_ACP_JS.exists():
        pytest.skip(
            "Claude ACP node entry not installed; run 'npm install' "
            "(@agentclientprotocol/claude-agent-acp) per the ACP runbook"
        )


def _ambient_user_server_names() -> list[str]:
    """Names in the operator's real user-global CLI config; best-effort."""
    override = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    base = Path(override).expanduser() if override else Path.home()
    config_file = base / ".claude.json"
    try:
        parsed = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    servers = parsed.get("mcpServers") if isinstance(parsed, dict) else None
    return sorted(servers) if isinstance(servers, dict) else []


def _project_scope_server_names(workspace: Path) -> list[str]:
    """Names the workspace's own ``.mcp.json`` declares; best-effort."""
    try:
        parsed = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    servers = parsed.get("mcpServers") if isinstance(parsed, dict) else None
    return sorted(servers) if isinstance(servers, dict) else []


def _armed_model(workspace: Path) -> AcpChatModel:
    model = ProviderFactory().create(
        Provider.CLAUDE, model=Model.LOW, workspace_root=workspace
    )
    assert isinstance(model, AcpChatModel)
    armed = model.with_mcp_servers(
        resolve_harness_mcp_servers([_RAG]), harness_allowed_tool_names([_RAG])
    )
    assert isinstance(armed, AcpChatModel)
    return armed


async def _run_turn(armed: AcpChatModel, prompt: str) -> str:
    messages = [SystemMessage(content="You are terse."), HumanMessage(content=prompt)]
    _, meta = _classify_acp_command(settings.acp_backend)
    try:
        return "".join([str(chunk.content) async for chunk in armed.astream(messages)])
    finally:
        leaked = armed._process
        if leaked is not None:
            await kill_process_tree(leaked, metadata=meta)


def _seed_workspace_canary(workspace: Path) -> dict[Path, str]:
    """Seed a live project-scope canary server and return the seeded contents."""
    canary_script = workspace / "canary_mcp.py"
    canary_script.write_text(_CANARY_SERVER, encoding="utf-8")
    mcp_json = workspace / ".mcp.json"
    mcp_json.write_text(
        json.dumps(
            {
                "mcpServers": {
                    _CANARY: {
                        "type": "stdio",
                        "command": sys.executable,
                        "args": [str(canary_script)],
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    settings_local = workspace / ".claude" / "settings.local.json"
    settings_local.parent.mkdir(parents=True)
    settings_local.write_text(
        json.dumps({"enableAllProjectMcpServers": True}, indent=2),
        encoding="utf-8",
    )
    return {
        path: path.read_text(encoding="utf-8")
        for path in (canary_script, mcp_json, settings_local)
    }


@pytest.mark.service
@pytest.mark.asyncio
async def test_strict_session_bounds_the_surface_to_the_injected_set(
    tmp_path: Path,
) -> None:
    _require_acp_entry()
    seeded = _seed_workspace_canary(tmp_path)
    ambient_names = _ambient_user_server_names()

    streamed = await _run_turn(
        _armed_model(tmp_path),
        "Call WaitForMcpServers, then reply with exactly one line:\n"
        "TOOLS=<comma-separated names of every tool you can call whose name "
        "starts with mcp__, or NONE>",
    )

    assert streamed.strip(), "Claude returned no streamed assistant text"
    # The injected server mounted and surfaced by exact name.
    assert "mcp__vaultspec-rag__search_codebase" in streamed, streamed
    # Nothing ambient joined the surface: not the live project-scope canary the
    # workspace itself enables, and none of the operator's user-global servers.
    assert f"mcp__{_CANARY}" not in streamed, streamed
    for name in ambient_names:
        assert f"mcp__{name}" not in streamed, (name, streamed)
    # Surfacing wrote nothing. The CLI itself may journal a permission decision
    # into the workspace's own settings.local.json - the same thing it does for
    # any interactive session in that cwd (ambient parity, not our residue) -
    # so that one file is asserted to still parse with the seeded key intact,
    # while the files no CLI feature writes must come back byte-identical.
    for path, content in seeded.items():
        if path.name == "settings.local.json":
            parsed = json.loads(path.read_text(encoding="utf-8"))
            assert parsed.get("enableAllProjectMcpServers") is True, path
        else:
            assert path.read_text(encoding="utf-8") == content, path
    unexpected = sorted(
        p.name
        for p in tmp_path.iterdir()
        if p.name not in {"canary_mcp.py", ".mcp.json", ".claude"}
    )
    assert unexpected == [], unexpected


@pytest.mark.service
@pytest.mark.asyncio
async def test_injected_rag_tool_completes_real_work_under_strict() -> None:
    _require_acp_entry()
    ambient_names = _ambient_user_server_names()
    project_names = _project_scope_server_names(_REPO_ROOT)
    # The regression premise: the repository's own project scope declares
    # servers (including a writable vault MCP) that must NOT surface.
    assert project_names, "expected the repository to declare project-scope MCP"

    streamed = await _run_turn(
        _armed_model(_REPO_ROOT),
        "First call WaitForMcpServers. Then call the tool "
        "mcp__vaultspec-rag__search_codebase with query='acp session setup'. "
        "Then reply with exactly two lines:\n"
        "TOOLS=<comma-separated names of every tool you can call whose name "
        "starts with mcp__, or NONE>\n"
        "RESULT=<OK if the search call returned any content, FAIL otherwise>",
    )

    assert streamed.strip(), "Claude returned no streamed assistant text"
    # Completed real work: the injected search tool surfaced, was called over
    # an indexed tree, and returned content.
    assert "mcp__vaultspec-rag__search_codebase" in streamed, streamed
    assert "RESULT=OK" in streamed.replace(" ", ""), streamed
    # No project-scope server joined the surface. The injected rag server
    # shares a name with the project's own entry, so the injected copy's
    # presence above is not a leak; every OTHER project name must be absent.
    for name in project_names:
        if name == _RAG:
            continue
        assert f"mcp__{name}" not in streamed, (name, streamed)
    for name in ambient_names:
        assert f"mcp__{name}" not in streamed, (name, streamed)
