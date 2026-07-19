"""Unit tests for the stdio authoring bridge config + binding transport (R4).

Pure logic, no subprocess or engine: the stdio ``mcpServers`` entry must spawn
our bridge module with the run's engine facts in ENV (never argv, so a process
listing never exposes the token — R7), and the binding must validate the stdio
transport (engine_base_url + run_id) exactly as it validates the HTTP one.
"""

from __future__ import annotations

import sys

import pytest

from ...authoring import AgentTool, CatalogSnapshot
from ...protocols.mcp.authoring_stdio import (
    ENV_ACTOR_TOKEN,
    ENV_BASE_URL,
    ENV_BEARER,
    ENV_RUN_ID,
)
from .._acp_authoring import (
    AUTHORING_MCP_SERVER_NAME,
    AUTHORING_STDIO_MODULE,
    AuthoringToolBinding,
    build_authoring_mcp_servers,
    build_authoring_stdio_mcp_servers,
)

_BEARER = "machine-bearer-secret"
_ACTOR = "actor-token-secret"
_ENGINE = "http://127.0.0.1:8767"
_RUN_ID = "run:abc123"


def _snapshot(*names: str) -> CatalogSnapshot:
    tools = tuple(
        AgentTool(
            name=name,
            description=name,
            input_schema={"type": "object"},
            risk_tier="read_only" if name == "read_context" else "mutating",
            permission_requirement="auto_permitted",
            idempotency_required=False,
            commands=(name,),
        )
        for name in (names or ("read_context", "propose_changeset"))
    )
    return CatalogSnapshot(schema_version="authoring.semantic_tools.v1", tools=tools)


def _stdio_binding() -> AuthoringToolBinding:
    return AuthoringToolBinding(
        snapshot=_snapshot(),
        bearer_token=_BEARER,
        actor_token=_ACTOR,
        engine_base_url=_ENGINE,
        run_id=_RUN_ID,
    )


def test_stdio_entry_spawns_bridge_module() -> None:
    entry = build_authoring_stdio_mcp_servers(_stdio_binding())[0]
    assert entry["name"] == AUTHORING_MCP_SERVER_NAME
    assert entry["command"] == sys.executable
    assert entry["args"] == ["-m", AUTHORING_STDIO_MODULE]
    # A stdio entry carries no "type"/"url" (the CLI keys stdio off the absence).
    assert "type" not in entry
    assert "url" not in entry


def test_authoring_bridge_is_a_provider_child_launch_spec_not_self_spawned() -> None:
    """Audit lock (W04.P11.S90): the per-run authoring bridge is a launch SPEC.

    The provider CLI spawns the ``python -m`` bridge as its own child, so the
    bridge is a descendant of the run-owned provider root and inherits that
    root's OS containment. This module never spawns a process itself, so there is
    no separate reaper to wire - the property that keeps the bridge contained.
    """
    import vaultspec_a2a.providers._acp_authoring as mod

    entry = build_authoring_stdio_mcp_servers(_stdio_binding())[0]
    # A child-launch spec the provider spawns: a command + args, no live process.
    assert entry["command"] == sys.executable
    assert entry["args"][:1] == ["-m"]
    # No process-spawn primitive is reachable from this spec-builder's namespace.
    for banned in (
        "subprocess",
        "Popen",
        "spawn_acp_process",
        "create_subprocess_exec",
        "ProcessContainment",
    ):
        assert not hasattr(mod, banned), (
            f"authoring spec builder must not spawn a process ({banned})"
        )


def test_stdio_entry_carries_engine_facts_in_env() -> None:
    entry = build_authoring_stdio_mcp_servers(_stdio_binding())[0]
    env = {item["name"]: item["value"] for item in entry["env"]}
    assert env[ENV_BASE_URL] == _ENGINE
    assert env[ENV_BEARER] == _BEARER
    assert env[ENV_ACTOR_TOKEN] == _ACTOR
    assert env[ENV_RUN_ID] == _RUN_ID


def test_stdio_tokens_never_appear_in_argv() -> None:
    # R7: tokens travel by env only; a process listing (command + args) must
    # never expose the bearer or actor token.
    entry = build_authoring_stdio_mcp_servers(_stdio_binding())[0]
    argv_blob = " ".join([entry["command"], *entry["args"]])
    assert _BEARER not in argv_blob
    assert _ACTOR not in argv_blob


def test_stdio_custom_python_executable() -> None:
    entry = build_authoring_stdio_mcp_servers(
        _stdio_binding(), python_executable="/opt/venv/bin/python"
    )[0]
    assert entry["command"] == "/opt/venv/bin/python"


def test_stdio_only_binding_rejects_http_builder() -> None:
    # A stdio-only binding has no server_url; the HTTP builder must fail loud.
    with pytest.raises(ValueError, match="requires server_url"):
        build_authoring_mcp_servers(_stdio_binding())


def test_http_only_binding_rejects_stdio_builder() -> None:
    http_binding = AuthoringToolBinding(
        snapshot=_snapshot(),
        bearer_token=_BEARER,
        actor_token=_ACTOR,
        server_url="http://127.0.0.1:8200/mcp",
    )
    with pytest.raises(ValueError, match="engine_base_url"):
        build_authoring_stdio_mcp_servers(http_binding)


def test_binding_requires_at_least_one_transport() -> None:
    with pytest.raises(ValueError, match=r"HTTP transport .* or a stdio transport"):
        AuthoringToolBinding(
            snapshot=_snapshot(), bearer_token=_BEARER, actor_token=_ACTOR
        )


def test_binding_rejects_non_loopback_engine() -> None:
    with pytest.raises(ValueError, match=r"not a .*loopback"):
        AuthoringToolBinding(
            snapshot=_snapshot(),
            bearer_token=_BEARER,
            actor_token=_ACTOR,
            engine_base_url="http://10.0.0.5:8767",
            run_id=_RUN_ID,
        )


def test_stdio_binding_rejects_write_tool() -> None:
    with pytest.raises(ValueError, match="filesystem-write"):
        AuthoringToolBinding(
            snapshot=_snapshot("read_context", "write_file"),
            bearer_token=_BEARER,
            actor_token=_ACTOR,
            engine_base_url=_ENGINE,
            run_id=_RUN_ID,
        )
