"""Real-subprocess proof that the worker wires bridged authoring tools.

No mocks: the worker node drives a real ACP subprocess (the protocol simulator)
through ``AcpChatModel``. When a run's :class:`AuthoringToolBinding` is attached,
the ``session/new`` the CLI receives must advertise the loopback authoring MCP
server carrying both auth layers — proving the wiring reaches a real subprocess.
Without a binding, ``session/new`` carries no MCP server, so the agent gains no
new surface by default.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from ....authoring import AgentTool, CatalogSnapshot
from ....providers._acp_authoring import (
    AUTHORING_MCP_SERVER_NAME,
    AuthoringToolBinding,
    authoring_allowed_tool_names,
)
from ....thread.actor_tokens import ActorTokenBundle
from ....worker.authoring_binding import AuthoringBindingProvider
from ....worker.catalog_store import RunCatalogStore
from ....worker.token_store import RunTokenStore
from ...nodes.worker import create_worker_node

if TYPE_CHECKING:
    from ....thread.state import TeamState

SIMULATOR_PATH = Path(__file__).parent.parent / "acp_simulator.py"
PYTHON_EXE = sys.executable

# The thread id _make_state carries; the provider keys tokens/catalog by it and
# the built binding's run_id is the thread_id.
_THREAD_ID = "test-thread-authoring"
_ENGINE_URL = "http://127.0.0.1:8767"


def _stdio_provider(
    *,
    engine_base_url: str = _ENGINE_URL,
    thread_id: str = _THREAD_ID,
    agent_id: str = "coder",
) -> AuthoringBindingProvider:
    """A real binding provider whose stores are pre-populated (no engine I/O).

    Registers *agent_id*'s token bundle and the run's catalog snapshot so
    ``binding_for`` builds a stdio binding without a live engine fetch - the real
    production seam (``AuthoringBindingProvider`` over ``RunTokenStore`` +
    ``RunCatalogStore``), exercised deterministically.
    """
    token_store = RunTokenStore()
    token_store.register(
        thread_id,
        ActorTokenBundle(
            tokens={agent_id: "actor-token-abc"},
            engine_bearer="machine-bearer-xyz",
        ),
    )
    catalog_store = RunCatalogStore()
    catalog_store.register(thread_id, _binding().snapshot)
    return AuthoringBindingProvider(
        engine_base_url=engine_base_url,
        token_store=token_store,
        catalog_store=catalog_store,
    )


def _make_state() -> TeamState:
    return {
        "active_agent": "coder",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Author a doc")],
        "next": "",
        "thread_id": "test-thread-authoring",
        "token_usage": {},
    }


def _binding(server_url: str = "http://127.0.0.1:8200/mcp") -> AuthoringToolBinding:
    snapshot = CatalogSnapshot(
        schema_version="authoring.semantic_tools.v1",
        tools=(
            AgentTool(
                name="read_context",
                description="read",
                input_schema={"type": "object"},
                risk_tier="read_only",
                permission_requirement="auto_permitted",
                idempotency_required=False,
                commands=("read_context",),
            ),
            AgentTool(
                name="propose_changeset",
                description="propose",
                input_schema={"type": "object"},
                risk_tier="mutating",
                permission_requirement="human_approval_required",
                idempotency_required=True,
                commands=("create_proposal",),
            ),
        ),
    )
    return AuthoringToolBinding(
        snapshot=snapshot,
        server_url=server_url,
        bearer_token="machine-bearer-xyz",
        actor_token="actor-token-abc",
    )


@pytest.mark.asyncio
async def test_binding_surfaces_authoring_server_to_real_subprocess(
    tmp_path: Path,
) -> None:
    """A bound worker turn makes the real CLI receive the authoring MCP server."""
    from ....providers.acp_chat_model import AcpChatModel

    record_file = tmp_path / "session_new.json"
    model = AcpChatModel(
        command=[
            PYTHON_EXE,
            str(SIMULATOR_PATH),
            "--response",
            "authored",
            "--record-session-new",
            str(record_file),
        ],
        # Armed run: an env auth token so config-home isolation engages (matching
        # test_stdio_binding_surfaces_bridge_into_isolated_home), which the
        # harness-armed spawn assertion now requires. Production-faithful: a real
        # armed run always carries its lane token.
        env_vars={"ANTHROPIC_AUTH_TOKEN": "env-auth-token"},
        workspace_root=str(tmp_path),
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
        autonomous=True,
        authoring_binding_provider=_stdio_provider(),
    )

    result = await node(_make_state())
    assert result["messages"][0].content == "authored"

    params = json.loads(record_file.read_text(encoding="utf-8"))
    servers = params["mcpServers"]
    assert len(servers) == 1
    entry = servers[0]
    # The provider builds a stdio binding, so session/new advertises the
    # spawn-a-bridge stdio entry (command + args), not an HTTP url.
    assert entry["name"] == AUTHORING_MCP_SERVER_NAME
    assert "url" not in entry
    assert entry["args"][0] == "-m"
    assert entry["args"][1].endswith("authoring_stdio")

    # The headless run auto-permits EXACTLY the bridged tool names so
    # the CLI can invoke them, and nothing else.
    allowed = params["_meta"]["claudeCode"]["options"]["allowedTools"]
    assert allowed == [
        "mcp__vaultspec-authoring__read_context",
        "mcp__vaultspec-authoring__propose_changeset",
    ]
    # A non-bridged mutating tool (e.g. the built-in Write) is NOT permitted.
    assert "Write" not in allowed
    assert not any(name == "mcp__vaultspec-authoring__*" for name in allowed)


def _stdio_binding(
    engine_base_url: str = "http://127.0.0.1:8767",
    run_id: str = "run:xyz",
) -> AuthoringToolBinding:
    return AuthoringToolBinding(
        snapshot=_binding().snapshot,
        bearer_token="machine-bearer-xyz",
        actor_token="actor-token-abc",
        engine_base_url=engine_base_url,
        run_id=run_id,
    )


@pytest.mark.asyncio
async def test_stdio_binding_wires_stdio_server_to_real_subprocess(
    tmp_path: Path,
) -> None:
    """A stdio binding makes session/new advertise the spawn-a-bridge entry.

    When the binding carries the engine transport (engine_base_url + run_id) the
    worker prefers the stdio bridge (a spawned subprocess). Neither session-injected
    transport surfaces to the model per the S20 registration-scope matrix, so this
    is a transport-mechanics choice, not a surfacing one. The session/new the real
    CLI receives must carry a stdio server entry (command + args, no url/type) whose
    env carries the run's engine facts — proving the wiring reaches a subprocess.
    """
    from ....providers._acp_authoring import AUTHORING_MCP_SERVER_NAME
    from ....providers.acp_chat_model import AcpChatModel

    record_file = tmp_path / "session_new.json"
    model = AcpChatModel(
        command=[
            PYTHON_EXE,
            str(SIMULATOR_PATH),
            "--response",
            "authored",
            "--record-session-new",
            str(record_file),
        ],
        # Armed run: an env auth token so config-home isolation engages (matching
        # test_stdio_binding_surfaces_bridge_into_isolated_home), which the
        # harness-armed spawn assertion now requires. Production-faithful: a real
        # armed run always carries its lane token.
        env_vars={"ANTHROPIC_AUTH_TOKEN": "env-auth-token"},
        workspace_root=str(tmp_path),
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
        autonomous=True,
        authoring_binding_provider=_stdio_provider(),
    )

    await node(_make_state())

    params = json.loads(record_file.read_text(encoding="utf-8"))
    servers = params["mcpServers"]
    assert len(servers) == 1
    entry = servers[0]
    assert entry["name"] == AUTHORING_MCP_SERVER_NAME
    # A stdio entry spawns a command; it carries no HTTP url/type.
    assert "url" not in entry
    assert "type" not in entry
    assert entry["args"][0] == "-m"
    assert entry["args"][1].endswith("authoring_stdio")
    env = {item["name"]: item["value"] for item in entry["env"]}
    # The advertised surface is serialized onto the CLI argv, so it carries
    # ${NAME} references and never the real values; the CLI expands each from
    # its own spawn environment at config-parse time. The sibling projection
    # test below asserts the other half - that the real values ARE hoisted.
    assert env["VAULTSPEC_AUTHORING_BASE_URL"] == "${VAULTSPEC_AUTHORING_BASE_URL}"
    # The provider sets run_id to the run's thread_id.
    assert env["VAULTSPEC_AUTHORING_RUN_ID"] == "${VAULTSPEC_AUTHORING_RUN_ID}"
    assert env["VAULTSPEC_AUTHORING_BEARER"] == "${VAULTSPEC_AUTHORING_BEARER}"
    # The real bearer never rides the argv-serialized surface.
    assert "machine-bearer-xyz" not in json.dumps(servers)

    # The exact allowlist is still threaded so the CLI can invoke the bridged
    # tools headless.
    allowed = params["_meta"]["claudeCode"]["options"]["allowedTools"]
    assert allowed == authoring_allowed_tool_names(_stdio_binding())


@pytest.mark.asyncio
async def test_stdio_binding_hoists_secrets_without_touching_the_workspace(
    tmp_path: Path,
) -> None:
    """The real spawn projects the bridge into the run workspace as placeholders.

    Drives ``AcpChatModel`` through a real subprocess so the armed-run branch
    projects the authoring bridge into the run workspace's ``.mcp.json`` and
    writes the confinement ``settings.local.json`` beside it - the config home
    is never redirected (the child inherits the operator's real environment).
    The subprocess reports its OWN cwd files and OWN environment: the projected
    ``.mcp.json`` must surface the bridge with ${VAR} placeholders and carry NO
    real token, the settings must enable exactly the declared name, and the real
    bearer must be present in the spawn env (proving
    ``config_home_authoring_entry`` is wired live, not dead).
    """
    from ....providers.acp_chat_model import AcpChatModel

    record_file = tmp_path / "config_home.json"
    model = AcpChatModel(
        command=[
            PYTHON_EXE,
            str(SIMULATOR_PATH),
            "--response",
            "authored",
            "--record-config-home",
            str(record_file),
        ],
        env_vars={},
        workspace_root=str(tmp_path),
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
        autonomous=True,
        authoring_binding_provider=_stdio_provider(),
    )

    await node(_make_state())

    recorded = json.loads(record_file.read_text(encoding="utf-8"))
    # No config-home redirect: the child resolves the operator's real login.
    assert recorded["config_home"] is None
    # Nothing is projected into the run workspace for MCP surfacing any more:
    # the declared-surface invariant rides the session advertisement plus strict
    # MCP mode, and the workspace projection channel it replaced was removed. A
    # run that wrote one would be re-opening the ambient surface this closed.
    assert recorded["workspace_mcp_json"] is None, (
        "MCP surfacing must not write into the run workspace"
    )
    # The real bearer is hoisted into the subprocess spawn env, which is where
    # the CLI expands the ${...} references the session surface carries.
    spawn_env = recorded["authoring_env"]
    assert spawn_env["VAULTSPEC_AUTHORING_BEARER"] == "machine-bearer-xyz"
    assert spawn_env["VAULTSPEC_AUTHORING_RUN_ID"] == _THREAD_ID
    # Nothing is left behind in the run workspace either, on any path.
    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / ".claude" / "settings.local.json").exists()


@pytest.mark.asyncio
async def test_no_binding_leaves_session_without_mcp_servers(
    tmp_path: Path,
) -> None:
    """Without a binding the real CLI receives no MCP server (no new surface)."""
    from ....providers.acp_chat_model import AcpChatModel

    record_file = tmp_path / "session_new.json"
    model = AcpChatModel(
        command=[
            PYTHON_EXE,
            str(SIMULATOR_PATH),
            "--response",
            "plain",
            "--record-session-new",
            str(record_file),
        ],
        env_vars={},
        workspace_root=str(tmp_path),
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
        autonomous=True,
    )

    result = await node(_make_state())
    assert result["messages"][0].content == "plain"

    params = json.loads(record_file.read_text(encoding="utf-8"))
    assert params["mcpServers"] == []


def test_worker_import_does_not_load_the_authoring_provider_module() -> None:
    """The authoring provider import stays deferred behind the binding guard.

    Real fresh interpreter, no mocks: importing the worker node must NOT drag in
    ``providers._acp_authoring``. That module costs roughly a second to load (it
    pulls the stdio bridge's env contract and the catalog codec), and a run
    without an authoring binding must never pay it. Hoisting the import to module
    scope would charge every worker turn - the import-time cold-start class that
    once cost this project a lost CLI tool-registration race - and this test is
    what fails when someone "tidies" the deferred import upward.
    """
    probe = (
        "import sys; import vaultspec_a2a.graph.nodes.worker; "
        "print('vaultspec_a2a.providers._acp_authoring' in sys.modules)"
    )
    proc = subprocess.run(
        [PYTHON_EXE, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    assert proc.stdout.strip() == "False", proc.stdout + proc.stderr
