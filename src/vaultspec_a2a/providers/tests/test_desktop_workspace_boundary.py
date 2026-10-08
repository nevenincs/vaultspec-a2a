"""Desktop callback roots cannot grant access to other capability planes."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING

import pytest

from ...control.state_layout import state_layout
from ...testing import armed_desktop_app_home, settings_override
from .._acp_request import jsonrpc_result
from .._acp_rpc_handlers import (
    _read_workspace_text,
    _write_workspace_text,
    on_fs_read_text_file,
    on_fs_write_text_file,
    sandbox_path,
)
from .._acp_types import AcpModelConfig, require_workspace_root

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from .._acp_types import AcpSessionContext


def _config(root: Path) -> AcpModelConfig:
    return AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=str(root),
        command=["echo"],
        env_vars={},
        mcp_servers=[],
        use_exec=False,
        provider=None,
        provider_command=None,
        auth_mode=None,
    )


def test_desktop_callbacks_reject_unsafe_roots_and_preserve_project_io(
    tmp_path: Path,
) -> None:
    home = tmp_path / "desktop"
    project = state_layout(home).workspaces_root / "project"
    state = home / "state"
    project.mkdir(parents=True)
    state.mkdir()
    sentinel = state / "credential.txt"
    sentinel.write_text("private-state-sentinel", encoding="utf-8")
    (project / "data.txt").write_text("project-sentinel", encoding="utf-8")
    with armed_desktop_app_home(home, provider_identity_launcher=None):
        for root in (home, state, tmp_path):
            with pytest.raises(ValueError, match="configured workspace root"):
                require_workspace_root(str(root), surface="provider cwd")
            with pytest.raises(ValueError, match="configured workspace root"):
                _read_workspace_text(str(sentinel), _config(root), line=None, limit=100)
            with pytest.raises(ValueError, match="configured workspace root"):
                _write_workspace_text(str(sentinel), "overwritten", _config(root))
        assert sentinel.read_text(encoding="utf-8") == "private-state-sentinel"
        config = _config(project)
        assert _read_workspace_text("data.txt", config, line=None, limit=100) == (
            "project-sentinel"
        )
        _write_workspace_text("output.txt", "project-output", config)
        assert (project / "output.txt").read_text(encoding="utf-8") == "project-output"
        link = project / "state-link"
        link.symlink_to(state, target_is_directory=True)
        for path in (
            str(sentinel),
            "../../state/credential.txt",
            "state-link/credential.txt",
        ):
            with pytest.raises(ValueError, match="escapes sandbox"):
                _read_workspace_text(path, config, line=None, limit=100)
            with pytest.raises(ValueError, match="escapes sandbox"):
                sandbox_path(path, config)


@pytest.mark.asyncio
async def test_desktop_rpc_refuses_state_content_and_reads_admitted_project(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    home = tmp_path / "desktop"
    project = state_layout(home).workspaces_root / "project"
    project.mkdir(parents=True)
    state_file = home / "credential.txt"
    state_file.write_text("private-state-sentinel", encoding="utf-8")
    (project / "data.txt").write_text("project-sentinel", encoding="utf-8")
    acp_session_context.session_id = "boundary-test"
    with armed_desktop_app_home(home, provider_identity_launcher=None):
        refused = await on_fs_read_text_file(
            1,
            {"sessionId": "boundary-test", "path": str(state_file)},
            acp_session_context,
            _config(home),
        )
        assert "error" in refused
        assert "result" not in refused
        assert "private-state-sentinel" not in str(refused)
        assert "configured workspace root" in str(refused)
        admitted = await on_fs_read_text_file(
            2,
            {"sessionId": "boundary-test", "path": "data.txt"},
            acp_session_context,
            _config(project),
        )
        assert admitted == jsonrpc_result(2, {"content": "project-sentinel"})


@contextmanager
def _swapping_link(entry: Path, target: Path) -> Generator[None]:
    """Replace a real entry concurrently; production Windows leases may refuse it."""
    parked = entry.with_name(f"{entry.name}-parked")
    directory = entry.is_dir()
    stop = threading.Event()
    swapped = threading.Event()
    errors: list[BaseException] = []

    def replace() -> None:
        try:
            while not stop.is_set():
                try:
                    entry.rename(parked)
                except PermissionError:
                    stop.wait(0.001)
                    continue
                try:
                    entry.symlink_to(target, target_is_directory=directory)
                    swapped.set()
                    stop.wait(0.001)
                except FileExistsError:
                    # A write can legitimately create the absent workspace leaf.
                    pass
                finally:
                    while entry.is_symlink():
                        try:
                            entry.unlink()
                        except PermissionError:
                            stop.wait(0.001)
                    while parked.exists():
                        try:
                            parked.replace(entry)
                        except PermissionError:
                            stop.wait(0.001)
        except BaseException as exc:
            errors.append(exc)
            swapped.set()

    worker = threading.Thread(target=replace, daemon=True)
    worker.start()
    try:
        assert swapped.wait(5), "replacement worker did not perform a real swap"
        assert not errors
        yield
    finally:
        stop.set()
        worker.join(5)
        assert not worker.is_alive(), "replacement worker did not release the entry"
        assert not errors


@pytest.mark.parametrize("directory", [False, True])
def test_desktop_read_stays_confined_during_real_replacement(
    tmp_path: Path, directory: bool
) -> None:
    home = tmp_path / "desktop"
    project = state_layout(home).workspaces_root / "project"
    safe = project / "safe"
    private = home / "state"
    safe.mkdir(parents=True)
    private.mkdir()
    workspace_file = safe / "data.txt"
    secret = private / "data.txt"
    workspace_file.write_text("workspace-control", encoding="utf-8")
    secret.write_text("private-state-sentinel", encoding="utf-8")
    entry, target = (safe, private) if directory else (workspace_file, secret)
    with armed_desktop_app_home(home, provider_identity_launcher=None):
        config = _config(project)
        assert _read_workspace_text("safe/data.txt", config, line=None, limit=None) == (
            "workspace-control"
        )
        with _swapping_link(entry, target):
            for _ in range(400):
                try:
                    content = _read_workspace_text(
                        "safe/data.txt", config, line=None, limit=None
                    )
                except (OSError, ValueError):
                    continue
                assert content == "workspace-control"
        assert _read_workspace_text("safe/data.txt", config, line=None, limit=None) == (
            "workspace-control"
        )


def test_desktop_write_does_not_truncate_replaced_private_leaf(tmp_path: Path) -> None:
    home = tmp_path / "desktop"
    project = state_layout(home).workspaces_root / "project"
    project.mkdir(parents=True)
    secret = home / "state.txt"
    secret.write_text("private-state-sentinel", encoding="utf-8")
    workspace_file = project / "data.txt"
    workspace_file.write_text("workspace-control", encoding="utf-8")
    with armed_desktop_app_home(home, provider_identity_launcher=None):
        config = _config(project)
        with _swapping_link(workspace_file, secret):
            for _ in range(400):
                with suppress(OSError, ValueError):
                    _write_workspace_text("data.txt", "workspace-output", config)
                assert secret.read_text(encoding="utf-8") == "private-state-sentinel"
        _write_workspace_text("nested/output.txt", "workspace-output", config)
        assert (project / "nested/output.txt").read_text(encoding="utf-8") == (
            "workspace-output"
        )
    assert secret.read_text(encoding="utf-8") == "private-state-sentinel"


def test_desktop_callbacks_refuse_hardlinked_state_without_truncation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "desktop"
    project = state_layout(home).workspaces_root / "project"
    project.mkdir(parents=True)
    secret = home / "state.txt"
    secret.write_text("private-state-sentinel", encoding="utf-8")
    alias = project / "alias.txt"
    alias.hardlink_to(secret)
    with armed_desktop_app_home(home, provider_identity_launcher=None):
        config = _config(project)
        with pytest.raises(ValueError, match="exactly one link"):
            _read_workspace_text("alias.txt", config, line=None, limit=None)
        with pytest.raises(ValueError, match="exactly one link"):
            _write_workspace_text("alias.txt", "overwritten", config)
    assert secret.read_text(encoding="utf-8") == "private-state-sentinel"


def test_callback_preserves_internal_path_aliases_and_rechecks_vault_writes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    safe = project / "safe"
    safe.mkdir(parents=True)
    (safe / "data.txt").write_text("workspace-control", encoding="utf-8")
    (project / "alias").symlink_to(safe, target_is_directory=True)
    vault = project / ".vault"
    vault.mkdir()
    vault_file = vault / "decision.md"
    vault_file.write_text("vault-control", encoding="utf-8")
    config = _config(project)
    assert _read_workspace_text("alias/data.txt", config, line=None, limit=None) == (
        "workspace-control"
    )
    _write_workspace_text("alias/../safe/data.txt", "workspace-output", config)
    assert (safe / "data.txt").read_text(encoding="utf-8") == "workspace-output"
    with pytest.raises(ValueError, match=r"\.vault"):
        _write_workspace_text(".vault/decision.md", "overwritten", config)
    assert vault_file.read_text(encoding="utf-8") == "vault-control"


if os.name == "posix":

    def test_callback_preserves_literal_posix_backslashes(tmp_path: Path) -> None:
        root = tmp_path / r"project\name"
        root.mkdir()
        target = root / r"data\text.txt"
        target.write_text("workspace-control", encoding="utf-8")
        config = _config(root)
        assert _read_workspace_text(target.name, config, line=None, limit=None) == (
            "workspace-control"
        )
        _write_workspace_text(target.name, "workspace-output", config)
        assert target.read_text(encoding="utf-8") == "workspace-output"

    def test_callback_preserves_search_only_ancestor_permissions(
        tmp_path: Path,
    ) -> None:
        ancestor = tmp_path / "search-only"
        project = ancestor / "project"
        project.mkdir(parents=True)
        target = project / "data.txt"
        target.write_text("workspace-control", encoding="utf-8")
        ancestor.chmod(0o111)
        try:
            with pytest.raises(PermissionError):
                list(ancestor.iterdir())
            assert target.read_text(encoding="utf-8") == "workspace-control"
            config = _config(project)
            assert _read_workspace_text("data.txt", config, line=None, limit=None) == (
                "workspace-control"
            )
            _write_workspace_text("data.txt", "workspace-output", config)
            assert target.read_text(encoding="utf-8") == "workspace-output"
        finally:
            ancestor.chmod(0o700)

    def test_confined_creation_preserves_compose_group_sharing(tmp_path: Path) -> None:
        with settings_override(
            provider_identity_launcher=tmp_path / "configured-launcher",
            provider_agent_gid=os.getgid(),
        ):
            _write_workspace_text(
                "nested/output.txt", "workspace-output", _config(tmp_path)
            )
        parent = tmp_path / "nested"
        target = parent / "output.txt"
        assert parent.stat().st_mode & 0o7777 == 0o2770
        assert target.stat().st_mode & 0o777 == 0o660
        assert target.stat().st_gid == os.getgid()
        assert target.read_text(encoding="utf-8") == "workspace-output"

    def test_callback_can_write_a_read_denied_regular_file(tmp_path: Path) -> None:
        target = tmp_path / "data.txt"
        target.write_text("workspace-control", encoding="utf-8")
        target.chmod(0o200)
        try:
            with pytest.raises(PermissionError):
                target.read_text(encoding="utf-8")
            _write_workspace_text("data.txt", "workspace-output", _config(tmp_path))
        finally:
            target.chmod(0o600)
        assert target.read_text(encoding="utf-8") == "workspace-output"

    def test_callback_refuses_fifo_without_blocking(tmp_path: Path) -> None:
        os.mkfifo(tmp_path / "data")
        config = _config(tmp_path)
        with pytest.raises(ValueError, match="regular"):
            _read_workspace_text("data", config, line=None, limit=None)
        with pytest.raises((OSError, ValueError)):
            _write_workspace_text("data", "overwritten", config)


if os.name == "nt":

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "component", [".vault.", ".vault ", ".. ", ".. .", "...", "name."]
    )
    async def test_callback_refuses_windows_creation_aliases_before_mutation(
        tmp_path: Path, acp_session_context: AcpSessionContext, component: str
    ) -> None:
        response = await on_fs_write_text_file(
            7,
            {
                "path": f"new/{component}/data.txt",
                "content": "overwritten",
                "sessionId": acp_session_context.session_id,
            },
            acp_session_context,
            _config(tmp_path),
        )
        if component.startswith(".vault"):
            result = response.get("result")
            assert isinstance(result, dict)
            assert result["denial_kind"] == "forbidden_actor"
        else:
            assert "error" in response
        assert list(tmp_path.iterdir()) == []
