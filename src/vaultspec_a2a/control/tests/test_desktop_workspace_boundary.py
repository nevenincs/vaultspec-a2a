"""Desktop workspace authority against real directories and stored inputs."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ...conftest import SqlitePosture
from ...context.metadata import ThreadMetadata
from ...database import (
    create_control_action,
    create_thread,
    list_active_thread_page,
    normalize_workspace_identity,
)
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...testing import DEFAULT_TEAM_PRESET, armed_desktop_app_home
from ...thread import RunWriteAuthority
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
from .._thread_metadata import dispatchable_workspace_root
from ..accepted_input import (
    AcceptedActionInput,
    freeze_accepted_input,
    restore_accepted_dispatch,
)
from ..dispatch import _restore_reconciling_dispatch
from ..dispatch_receipts import (
    bind_graph_action_receipt,
    prepare_graph_action_receipt,
)
from ..state_layout import state_layout
from ..thread_service import process_metadata
from ..workspace import require_admitted_workspace_root

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.parametrize(
    "target",
    [
        ".",
        "credentials",
        "state",
        "runtime",
        "procs",
        "receipts",
        "tmp/homes",
        "snapshots",
        "../outside",
        "..",
    ],
)
def test_desktop_refuses_state_outside_projects_and_ancestors(
    tmp_path: Path, target: str
) -> None:
    home = tmp_path / "desktop"
    project = state_layout(home).workspaces_root / "project"
    project.mkdir(parents=True)
    forbidden = home / target
    forbidden.mkdir(parents=True, exist_ok=True)
    with armed_desktop_app_home(home, workspace_root=None):
        with pytest.raises(ValueError, match="configured workspace root"):
            require_admitted_workspace_root(forbidden)
        with pytest.raises(ValueError, match="configured workspace root"):
            process_metadata(ThreadMetadata(workspace_root=str(forbidden)), "bad", None)
        assert (
            dispatchable_workspace_root(json.dumps({"workspace_root": str(forbidden)}))
            is None
        )
        root, _nickname, metadata = process_metadata(
            ThreadMetadata(workspace_root=str(project)), "good", None
        )
        assert root == project.resolve()
        assert json.loads(metadata)["workspace_root"] == str(project.resolve())
        assert dispatchable_workspace_root(metadata) == str(project.resolve())


def test_desktop_refuses_candidate_and_boundary_symlink_redirects(
    tmp_path: Path,
) -> None:
    home = tmp_path / "desktop"
    managed = state_layout(home).workspaces_root
    managed.mkdir(parents=True)
    state = home / "state"
    state.mkdir()
    escape = managed / "escape"
    escape.symlink_to(state, target_is_directory=True)
    with armed_desktop_app_home(home):
        with pytest.raises(ValueError, match="configured workspace root"):
            require_admitted_workspace_root(escape)
        assert (
            dispatchable_workspace_root(json.dumps({"workspace_root": str(escape)}))
            is None
        )
        escape.unlink()
        managed.rmdir()
        managed.symlink_to(state, target_is_directory=True)
        with pytest.raises(ValueError, match="configured workspace root redirects"):
            require_admitted_workspace_root(state)


def test_desktop_normalizes_project_aliases_before_enforcing_authority(
    tmp_path: Path,
) -> None:
    home = tmp_path / "desktop"
    managed = state_layout(home).workspaces_root
    project = managed / "project"
    project.mkdir(parents=True)
    aliases = [str(project), project.as_posix(), str(project / ".." / "project")]
    forbidden_aliases = [str(home), str(project / ".." / "..")]
    if os.name == "nt":
        aliases.extend([str(project).upper(), "\\\\?\\" + str(project)])
        forbidden_aliases.append("\\\\?\\" + str(home))
    with armed_desktop_app_home(home):
        for alias in aliases:
            admitted = require_admitted_workspace_root(alias)
            assert admitted.samefile(project)
            if alias.startswith("\\\\?\\"):
                assert str(admitted).startswith("\\\\?\\")
        for alias in forbidden_aliases:
            with pytest.raises(ValueError, match="configured workspace root"):
                require_admitted_workspace_root(alias)


def test_frozen_dispatch_rechecks_desktop_authority_and_cancel_remains_available(
    tmp_path: Path,
) -> None:
    home = tmp_path / "desktop"
    project = state_layout(home).workspaces_root / "project"
    project.mkdir(parents=True)
    definition = freeze_graph_definition(
        load_team_config(DEFAULT_TEAM_PRESET, workspace_root=project),
        workspace_root=project,
    )
    with armed_desktop_app_home(home):
        for root in (home, project):
            request = DispatchRequest(
                action="resume",
                thread_id="saved-run",
                workspace_root=str(root),
                team_preset=DEFAULT_TEAM_PRESET,
                graph_definition=definition,
                recursion_limit=25,
            )
            accepted = AcceptedActionInput.model_validate(
                freeze_accepted_input(request, intent={})
            )
            if root == home:
                with pytest.raises(ValueError, match="configured workspace root"):
                    restore_accepted_dispatch(accepted, dispatch_id="retry")
            else:
                restored = restore_accepted_dispatch(accepted, dispatch_id="retry")
                assert restored.workspace_root == str(project.resolve())
        cancellation = DispatchRequest(
            action="cancel",
            thread_id="saved-run",
            workspace_root=str(home),
            recursion_limit=25,
        )
        accepted_cancel = AcceptedActionInput.model_validate(
            freeze_accepted_input(cancellation, intent={})
        )
        assert (
            restore_accepted_dispatch(accepted_cancel, dispatch_id="cancel").action
            == "cancel"
        )


@pytest.mark.asyncio
@pytest.mark.sqlite_engine(SqlitePosture.TRANSACTIONS)
async def test_saved_project_aliases_remain_valid_for_restart_reconciliation(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    home = tmp_path / "desktop"
    project = state_layout(home).workspaces_root / "project"
    project.mkdir(parents=True)
    aliases = [str(project / ".." / "project")]
    if os.name == "nt":
        aliases.append("\\\\?\\" + str(project))
    definition = freeze_graph_definition(
        load_team_config(DEFAULT_TEAM_PRESET, workspace_root=project),
        workspace_root=project,
    )
    with armed_desktop_app_home(home):
        async with session_factory() as db:
            for index, alias in enumerate(aliases):
                run_id = f"saved-alias-{index}"
                dispatch_id = f"saved-receipt-{index}"
                request = DispatchRequest(
                    action="resume",
                    thread_id=run_id,
                    workspace_root=alias,
                    team_preset=DEFAULT_TEAM_PRESET,
                    graph_definition=definition,
                    recursion_limit=25,
                )
                thread = await create_thread(
                    db,
                    thread_id=run_id,
                    status=ThreadStatus.RECONCILING,
                    team_preset=DEFAULT_TEAM_PRESET,
                    metadata=json.dumps({"workspace_root": alias}),
                    write_authority=RunWriteAuthority(
                        0, 1, ControlActionType.RESUME, dispatch_id
                    ),
                )
                await create_control_action(
                    db,
                    thread_id=run_id,
                    action_type=ControlActionType.RESUME,
                    idempotency_key=dispatch_id,
                    dispatch_id=dispatch_id,
                    payload=freeze_accepted_input(request, intent={}),
                    recovery_deadline_at=datetime(2100, 1, 1, tzinfo=UTC),
                )
                assert (
                    await prepare_graph_action_receipt(
                        db, thread_id=run_id, dispatch_id=dispatch_id
                    )
                    is not None
                )
                await db.commit()
                restored = await _restore_reconciling_dispatch(
                    db, thread, {}, str(project.resolve())
                )
                assert restored is not None
                assert require_admitted_workspace_root(
                    restored.dispatch.workspace_root or ""
                ).samefile(project)
                # The receipt the leased delivery binds is this action's own.
                bound = await bind_graph_action_receipt(db, restored.dispatch)
                assert bound.graph_action_receipt is not None
                discovered = await list_active_thread_page(
                    db,
                    limit=100,
                    workspace_root=normalize_workspace_identity(
                        require_admitted_workspace_root(alias)
                    ),
                )
                assert run_id in {row.id for row in discovered}
