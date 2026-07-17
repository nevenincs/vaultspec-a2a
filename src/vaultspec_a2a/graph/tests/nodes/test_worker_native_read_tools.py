"""Real-subprocess proof that document-authoring roles get the native read floor.

No mocks: the worker node drives a real ACP subprocess (the protocol simulator)
through ``AcpChatModel``. For an autonomous document-authoring role, the
``session/new`` the CLI receives must auto-permit the native Read/Grep/Glob
built-ins by exact name — the deterministic grounding floor — while a
non-document role and a human-in-loop run receive no such grant. When an
authoring binding is also present, the read built-ins union with the bridged
authoring tool names without dropping either.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from vaultspec_a2a.providers._acp_authoring import authoring_allowed_tool_names

from ...nodes.worker import (
    NATIVE_READ_TOOL_NAMES,
    _compose_native_read_tools,
    create_worker_node,
)
from .test_worker_authoring_wiring import _binding, _stdio_provider

if TYPE_CHECKING:
    from vaultspec_a2a.thread.state import TeamState

SIMULATOR_PATH = Path(__file__).parent.parent / "acp_simulator.py"
PYTHON_EXE = sys.executable


def _make_state() -> TeamState:
    return {
        "active_agent": "researcher",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research a topic")],
        "next": "",
        "thread_id": "test-thread-native-read",
        "token_usage": {},
    }


def _model(record_file: Path, tmp_path: Path):
    from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

    return AcpChatModel(
        command=[
            PYTHON_EXE,
            str(SIMULATOR_PATH),
            "--response",
            "researched",
            "--record-session-new",
            str(record_file),
        ],
        env_vars={},
        workspace_root=str(tmp_path),
    )


def _allowed_tools(params: dict) -> list[str]:
    meta = params.get("_meta", {})
    return meta.get("claudeCode", {}).get("options", {}).get("allowedTools", [])


@pytest.mark.asyncio
async def test_document_role_autonomous_permits_native_read_builtins(
    tmp_path: Path,
) -> None:
    """An autonomous document role makes the real CLI auto-permit Read/Grep/Glob."""
    record_file = tmp_path / "session_new.json"
    node = create_worker_node(
        model=_model(record_file, tmp_path),
        system_prompt="You are a researcher.",
        name="researcher",
        autonomous=True,
        role="researcher",
    )

    result = await node(_make_state())
    assert result["messages"][0].content == "researched"

    params = json.loads(record_file.read_text(encoding="utf-8"))
    assert _allowed_tools(params) == list(NATIVE_READ_TOOL_NAMES)
    # Exact names only — never a wildcard grant.
    assert "*" not in "".join(_allowed_tools(params))


@pytest.mark.asyncio
async def test_native_read_tools_union_with_authoring_allowlist(
    tmp_path: Path,
) -> None:
    """The read built-ins union with the bridged authoring names, no drops."""
    record_file = tmp_path / "session_new.json"
    node = create_worker_node(
        model=_model(record_file, tmp_path),
        system_prompt="You are a researcher.",
        name="researcher",
        autonomous=True,
        role="researcher",
        authoring_binding_provider=_stdio_provider(
            thread_id="test-thread-native-read", agent_id="researcher"
        ),
    )

    await node(_make_state())

    params = json.loads(record_file.read_text(encoding="utf-8"))
    allowed = _allowed_tools(params)
    assert allowed == [
        *authoring_allowed_tool_names(_binding()),
        *NATIVE_READ_TOOL_NAMES,
    ]


@pytest.mark.asyncio
async def test_non_document_role_gets_no_native_read_builtins(
    tmp_path: Path,
) -> None:
    """A non-document role (role=None coder) receives no read-built-in grant."""
    record_file = tmp_path / "session_new.json"
    node = create_worker_node(
        model=_model(record_file, tmp_path),
        system_prompt="You are a coder.",
        name="coder",
        autonomous=True,
        role=None,
    )

    await node(_make_state())

    params = json.loads(record_file.read_text(encoding="utf-8"))
    assert _allowed_tools(params) == []


@pytest.mark.asyncio
async def test_human_in_loop_document_role_gets_no_allowlist(
    tmp_path: Path,
) -> None:
    """A human-in-loop document run keeps its prompt — no auto-permit grant."""
    record_file = tmp_path / "session_new.json"
    node = create_worker_node(
        model=_model(record_file, tmp_path),
        system_prompt="You are a researcher.",
        name="researcher",
        autonomous=False,
        role="researcher",
    )

    await node(_make_state())

    params = json.loads(record_file.read_text(encoding="utf-8"))
    assert _allowed_tools(params) == []


class TestComposeNativeReadTools:
    """The native-read composition is exact, role-scoped, and autonomous-only."""

    def _fresh_model(self):
        from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

        return AcpChatModel(command=["echo"], env_vars={}, workspace_root="/tmp/ws")

    def test_autonomous_document_role_unions_read_names(self) -> None:
        from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

        wired = _compose_native_read_tools(
            self._fresh_model(), autonomous=True, role="researcher"
        )
        assert isinstance(wired, AcpChatModel)
        assert wired.allowed_tools == list(NATIVE_READ_TOOL_NAMES)

    def test_non_document_role_is_unchanged(self) -> None:
        from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

        model = self._fresh_model()
        wired = _compose_native_read_tools(model, autonomous=True, role=None)
        assert isinstance(wired, AcpChatModel)
        assert wired.allowed_tools == []

    def test_human_in_loop_is_unchanged(self) -> None:
        from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

        model = self._fresh_model()
        wired = _compose_native_read_tools(model, autonomous=False, role="researcher")
        assert isinstance(wired, AcpChatModel)
        assert wired.allowed_tools == []

    def test_existing_allowlist_is_preserved_and_deduped(self) -> None:
        from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

        model = self._fresh_model().model_copy(
            update={"allowed_tools": ["mcp__x__y", "Read"]}
        )
        wired = _compose_native_read_tools(model, autonomous=True, role="synthesist")
        assert isinstance(wired, AcpChatModel)
        # Pre-existing entries kept in place; only the missing read names appended.
        assert wired.allowed_tools == ["mcp__x__y", "Read", "Grep", "Glob"]
