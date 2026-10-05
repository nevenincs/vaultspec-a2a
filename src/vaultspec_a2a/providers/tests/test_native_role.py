"""Real role-home lifecycle and invocation copies preserve selected authority."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from ...desktop.native_isolation import NativeWorkspaceAuthority
from ...desktop.tests.test_native_isolation import _authority, _install_runtime
from ...testing import settings_override
from ...utils.process import ProcessContainmentError
from .._native_role import (
    bind_model_native_workspace,
    prepare_acp_role,
    prepare_native_version_probe,
    require_native_workspace,
    role_environment,
)
from .._subprocess import kill_process_tree, spawn_acp_process
from ..acp_chat_model import AcpChatModel
from ..binary_version import probe_binary_version
from ..cli_resolution import ProviderRuntimeUnavailableError
from ..codex_chat_model import CodexChatModel

if TYPE_CHECKING:
    from pathlib import Path


def test_worker_binding_is_private_and_does_not_recapture_changed_project(
    tmp_path: Path,
) -> None:
    roots = _authority(tmp_path)
    models = (
        AcpChatModel(
            command=[sys.executable], workspace_root=str(roots.workspace.path)
        ),
        CodexChatModel(workspace_root=str(roots.workspace.path)),
    )
    with settings_override(
        desktop_app_home=roots.app_home.path, capsule_assets_root=roots.capsule.path
    ):
        scopes: list[NativeWorkspaceAuthority] = []
        for model in models:
            bound = bind_model_native_workspace(model, workspace=roots.workspace.path)
            assert isinstance(bound, (AcpChatModel, CodexChatModel))
            assert bound is not model
            assert model._native_workspace is None
            scope = bound._native_workspace
            assert isinstance(scope, NativeWorkspaceAuthority)
            scopes.append(scope)
            assert "_native_workspace" not in bound.model_dump()
            require_native_workspace(scope, roots.workspace.path)
            sibling = roots.workspace.path.with_name("sibling")
            sibling.mkdir(exist_ok=True)
            with pytest.raises(ProcessContainmentError, match="differs"):
                require_native_workspace(scope, sibling)
        with pytest.raises(ProcessContainmentError, match="worker binding"):
            require_native_workspace(None, roots.workspace.path)
        roots.workspace.path.rename(roots.workspace.path.with_name("original"))
        roots.workspace.path.mkdir()
        with pytest.raises(OSError, match="changed"):
            scopes[-1].for_home(roots.home.path)


@pytest.mark.asyncio
async def test_prepared_role_contains_selected_channel_and_cleans_home(
    tmp_path: Path,
) -> None:
    roots = _authority(tmp_path)
    scope = NativeWorkspaceAuthority(roots.app_home, roots.capsule, roots.workspace)
    if sys.platform != "linux":
        with pytest.raises(ProcessContainmentError, match="requires Linux"):
            async with prepare_acp_role(scope, environment={}, provider="claude"):
                raise AssertionError("unsupported platform prepared a role")
        return
    node = _install_runtime(roots)
    private = roots.app_home.path / "private-control"
    private.write_text("service-state-control", encoding="utf-8")
    with pytest.raises(ProcessContainmentError, match="credential store"):
        async with prepare_acp_role(scope, environment={}, provider="claude"):
            raise AssertionError("unsupported store prepared a role")
    environment = {
        **os.environ,
        "CLAUDE_CODE_OAUTH_TOKEN": "synthetic-selected-channel",
    }
    async with prepare_acp_role(
        scope, environment=environment, provider="claude"
    ) as launch:
        assert launch is not None
        home = launch.home.path
        assert home != roots.home.path
        script = (
            "const fs=require('fs'); let denied=false;"
            + f"try {{fs.readFileSync({json.dumps(str(private))});}}"
            + "catch(e){denied=e.code==='ENOENT';}"
            + "fs.writeFileSync(process.env.CLAUDE_CONFIG_DIR+'/role-state','owned');"
            + "console.log(JSON.stringify({denied,"
            + "selected:process.env.CLAUDE_CODE_OAUTH_TOKEN==="
            + "'synthetic-selected-channel',"
            + "home:process.env.HOME}));"
        )
        process = await spawn_acp_process(
            [str(node), "-e", script],
            {**environment, **role_environment(launch)},
            str(scope.workspace.path),
            native_authority=launch,
        )
        try:
            output, error = await asyncio.wait_for(process.communicate(), timeout=15)
            assert process.returncode == 0, error.decode()
            assert json.loads(output) == {
                "denied": True,
                "selected": True,
                "home": str(home),
            }
            assert (home / "role-state").read_text() == "owned"
        finally:
            await kill_process_tree(process)
    assert not home.exists()
    assert roots.home.path.is_dir()
    assert private.read_text() == "service-state-control"


@pytest.mark.asyncio
async def test_model_startup_refusals_remove_prepared_role_homes(
    tmp_path: Path,
) -> None:
    roots = _authority(tmp_path)
    scope = NativeWorkspaceAuthority(roots.app_home, roots.capsule, roots.workspace)
    # No provider is substituted: the real resolver refuses the absent capsule
    # CLI, and the shared native gate refuses the real Codex acquisition path.
    models = (
        AcpChatModel(
            command=[sys.executable],
            workspace_root=str(roots.workspace.path),
            provider="claude",
            env_vars={"CLAUDE_CODE_OAUTH_TOKEN": "synthetic-selected-channel"},
        ).with_native_workspace(scope),
        CodexChatModel(
            command=[sys.executable],
            workspace_root=str(roots.workspace.path),
            codex_home=str(tmp_path / "uncredentialed-source"),
        ).with_native_workspace(scope),
    )
    homes = roots.home.path.parent
    before = set(homes.iterdir())
    with settings_override(
        desktop_app_home=roots.app_home.path,
        a2a_home=roots.app_home.path,
        capsule_assets_root=roots.capsule.path,
    ):
        for model in models:
            with pytest.raises(
                (ProcessContainmentError, ProviderRuntimeUnavailableError)
            ):
                await model.ainvoke([HumanMessage(content="startup cleanup control")])
            assert set(homes.iterdir()) == before
    assert models[0]._native_authority is None
    assert models[0]._state.session.session_busy is False


def test_version_probe_home_is_empty_bound_and_removed(tmp_path: Path) -> None:
    roots = _authority(tmp_path)
    scope = NativeWorkspaceAuthority(roots.app_home, roots.capsule, roots.workspace)
    if sys.platform != "linux":
        with (
            pytest.raises(ProcessContainmentError, match="requires Linux"),
            prepare_native_version_probe(scope),
        ):
            raise AssertionError("unsupported platform prepared a probe")
        return
    _install_runtime(roots)
    with prepare_native_version_probe(scope) as launch:
        assert launch is not None
        home = launch.home.path
        assert list(home.iterdir()) == []
        assert (
            probe_binary_version(
                roots.capsule.path / "isolation/bin/bubblewrap", native_authority=launch
            )
            == "0.11.1"
        )
    assert not home.exists()
    assert roots.home.path.is_dir()
