"""Real Codex turns preserve one runtime identity across graph dispatch paths."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from langchain_core.messages import HumanMessage

from ...database.models import ProviderRuntimeIdentityModel
from ...database.tests._backends import migrated_session_factory
from ...database.thread_repository import create_thread
from ...providers.binary_version import probe_binary_version
from ...providers.codex_chat_model import CodexChatModel
from ...providers.factory import ProviderFactory
from ...testing import declared_lane_model_value
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ...worker.runtime_identity_port import SqlRuntimeIdentityPort
from .._compiler_research import _make_research_producer
from ..enums import Provider
from ..nodes.worker import create_worker_node

if TYPE_CHECKING:
    from pathlib import Path

    from ...conftest import ExternalPrerequisiteRule
    from ...thread.state import TeamState


@pytest.mark.service
@pytest.mark.asyncio
async def test_worker_and_research_turns_share_first_runtime_identity(
    tmp_path: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """Both graph routes use the real selected lane and one durable run row."""
    external_prerequisite("codex-cli")
    external_prerequisite("codex-credential")
    served, reason = await declared_lane_model_value(Provider.CODEX.value, tmp_path)
    if served is None:
        external_prerequisite.absent("provider-catalog-live-selection", reason)
    async with migrated_session_factory("sqlite", tmp_path) as (_target, factory):
        async with factory() as session:
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                thread_id="graph-identity-live",
                status=ThreadStatus.RUNNING,
            )
            await session.commit()
        model = ProviderFactory().create(
            Provider.CODEX, model=served, workspace_root=tmp_path
        )
        assert isinstance(model, CodexChatModel)
        observed_version = probe_binary_version(model.command[0])
        port = SqlRuntimeIdentityPort(factory)
        state = cast(
            "TeamState",
            {
                "active_agent": "coder",
                "artifacts": [],
                "current_plan": [],
                "messages": [HumanMessage(content="Reply with one word: pong")],
                "next": "",
                "thread_id": "graph-identity-live",
                "token_usage": {},
            },
        )
        worker = create_worker_node(
            model=model,
            system_prompt="You are terse.",
            name="coder",
            autonomous=True,
            workspace_root=tmp_path,
            runtime_identity_port=port,
        )
        result = await worker(state)
        assert isinstance(result, dict)
        assert result["messages"]
        async with factory() as session:
            first = await session.get(
                ProviderRuntimeIdentityModel,
                ("graph-identity-live", "codex", "codex-app-server"),
            )
            assert first is not None
            first_native_id = first.provider_session_id
            assert first_native_id

        producer = _make_research_producer(
            model,
            "You are terse. Reply with one word: pong",
            workspace_root=tmp_path,
            autonomous=True,
            runtime_identity_port=port,
        )
        finding = await producer(
            state,
            {"thread_id": "research-1", "topic": "pong", "instructions": "Reply pong"},
        )
        assert finding["claim"]
        async with factory() as session:
            row = await session.get(
                ProviderRuntimeIdentityModel,
                ("graph-identity-live", "codex", "codex-app-server"),
            )
            assert row is not None
            assert row.provider_session_id == first_native_id
            assert row.cli_version == observed_version
            assert row.managed_policy_present is None
