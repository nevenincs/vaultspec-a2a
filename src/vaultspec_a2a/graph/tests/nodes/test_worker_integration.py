"""Integration tests for the worker node using the ACP simulator."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import BaseMessage, HumanMessage

from ....testing import (
    ACP_SIMULATOR_PATH,
    simulator_command,
)
from ....tests._write_authority import make_test_write_authority
from ...nodes.worker import WorkerNode, WorkerNodeOptions, create_worker_node

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ....thread.state import TeamState

# The ACP lane now requires the run's active project at construction - it is no
# longer inferred from the serving process - so these integration models name a
# real directory the way a dispatched run does.
_PROJECT = Path(__file__).resolve().parents[4]
PYTHON_EXE = sys.executable


def _make_state() -> TeamState:
    return {
        "active_agent": "coder",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Write code")],
        "next": "",
        "thread_id": "test-thread",
        "token_usage": {},
    }


@pytest.mark.asyncio
async def test_worker_execution_integration() -> None:
    """Worker node executes correctly using a real ACP subprocess."""
    from ....providers.acp_chat_model import AcpChatModel

    model = AcpChatModel(
        command=simulator_command("--response", "HelloWorld"),
        env_vars={},
        workspace_root=str(_PROJECT),
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
    )

    result = await node(_make_state())
    assert isinstance(result, dict)
    assert "messages" in result
    assert result["messages"][0].content == "HelloWorld"
    assert result["messages"][0].name == "coder"


@pytest.mark.asyncio
async def test_acp_worker_records_initialized_subprocess_identity(
    tmp_path: Path,
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A real ACP subprocess records initialize and session/new before its prompt."""
    from ....database.models import ProviderRuntimeIdentityModel
    from ....database.thread_repository import create_thread
    from ....providers._factory_commands import ProviderCommand
    from ....providers.acp_chat_model import AcpChatModel
    from ....providers.binary_version import probe_binary_version
    from ....thread.enums import ThreadStatus
    from ....worker.runtime_identity_port import SqlRuntimeIdentityPort

    async with migrated_session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="acp-worker-identity",
            status=ThreadStatus.RUNNING,
        )
        await session.commit()
    command = simulator_command("--response", "pong")
    model = AcpChatModel(
        command=command,
        provider_command=ProviderCommand(
            argv=tuple(command),
            runtime_authority="test_subprocess",
            command_origin="test_subprocess",
            command_kind="acp_simulator",
            command_executable=Path(PYTHON_EXE).name,
            command_target=str(ACP_SIMULATOR_PATH),
        ),
        provider="kimi",
        execution_mode="kimi-code-acp",
        auth_mode="test",
        acp_family="kimi",
        env_vars={},
        workspace_root=str(tmp_path),
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are terse.",
        name="coder",
        options=WorkerNodeOptions(
            runtime_identity_port=SqlRuntimeIdentityPort(migrated_session_factory)
        ),
    )
    state = _make_state()
    state["thread_id"] = "acp-worker-identity"
    result = await node(state)
    assert isinstance(result, dict)
    assert result["messages"][0].content == "pong"
    async with migrated_session_factory() as session:
        row = await session.get(
            ProviderRuntimeIdentityModel,
            ("acp-worker-identity", "kimi", "kimi-code-acp"),
        )
        assert row is not None
        assert row.adapter_name == "acp-simulator"
        assert row.adapter_version == "1.0.0"
        assert row.cli_version == probe_binary_version(PYTHON_EXE)
        assert row.provider_session_id
        assert row.managed_policy_present is None


@pytest.mark.asyncio
async def test_worker_context_compaction_integration() -> None:
    """Worker node handles large context with compaction."""
    from ....providers.acp_chat_model import AcpChatModel

    model = AcpChatModel(
        command=simulator_command("--response", "Compacted"),
        env_vars={},
        workspace_root=str(_PROJECT),
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
    )

    big_messages: list[BaseMessage] = [HumanMessage(content="x" * 500_000)]
    state = _make_state()
    state["messages"] = big_messages

    result = await node(state)
    assert isinstance(result, dict)
    assert result["messages"][0].content == "Compacted"


@pytest.mark.asyncio
async def test_worker_error_handling_integration() -> None:
    """Worker node handles ACP subprocess errors correctly."""
    from ....providers.acp_chat_model import AcpChatModel

    model = AcpChatModel(
        command=simulator_command("--error", "Internal agent failure"),
        env_vars={},
        workspace_root=str(_PROJECT),
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
    )

    with pytest.raises(Exception) as excinfo:
        await node(_make_state())

    error_str = str(excinfo.value)
    if excinfo.value.__cause__:
        error_str += " " + str(excinfo.value.__cause__)

    assert "Internal agent failure" in error_str


@pytest.mark.asyncio
async def test_worker_turn_consumes_a_rejection_and_keeps_an_approval() -> None:
    """A rejection is spent by the turn it routed; a grant outlives it.

    The execution approval is per-thread durable state - the human approved
    this thread's plan, not one turn of it - so a turn that cleared it asked
    the same human the same question before every later exec turn. A
    rejection is the opposite: it routed one revision and has no meaning
    after it.
    """
    from ....providers.acp_chat_model import AcpChatModel

    def _node() -> WorkerNode:
        model = AcpChatModel(
            command=simulator_command("--response", "approved once"),
            env_vars={},
            workspace_root=str(_PROJECT),
        )
        return create_worker_node(
            model=model,
            system_prompt="You are a coder.",
            name="coder",
        )

    granted = _make_state()
    granted["approval_status"] = "approved"
    granted["approval_request_id"] = "approval-1"
    result = await _node()(granted)

    assert isinstance(result, dict)
    assert result["messages"][0].content == "approved once"
    assert result["approval_status"] == "approved"
    # The linkage rides with the approval it belongs to.
    assert "approval_request_id" not in result

    rejected = _make_state()
    rejected["approval_status"] = "rejected"
    rejected["approval_request_id"] = "approval-1"
    result = await _node()(rejected)

    assert isinstance(result, dict)
    assert result["approval_status"] is None
    assert result["approval_request_id"] is None
