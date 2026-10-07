"""Exercise desktop privacy failures against real filesystem state."""

from __future__ import annotations

import ctypes
import os
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

import pytest

from ...control.config import Settings
from .._platform_acl import (
    _windows_system_executable,
    path_is_owner_restricted,
    windows_current_user_sid,
)
from ..migration import MigrationStage, initialize_fresh_stores, migrate_stores
from ..profile import (
    DesktopProfile,
    DesktopProfileError,
    derive_state_paths,
    provisioned_directories,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator

    from ..migration import MigrationResult


def _profile(home: Path) -> DesktopProfile:
    # Capsule validation is separate from the state-protection boundary.
    return DesktopProfile(home, home.parent / "capsule", derive_state_paths(home))


def _make_public(path: Path) -> None:
    if os.name == "nt":
        subprocess.run(
            [
                _windows_system_executable("icacls.exe"),
                str(path),
                "/grant",
                "*S-1-1-0:F",
            ],
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        path.chmod(0o666)
    assert not path_is_owner_restricted(path)


@pytest.mark.parametrize("store", ["database_path", "checkpoint_path"])
def test_existing_databases_and_side_files_are_restricted(
    tmp_path: Path, store: str
) -> None:
    profile = _profile(tmp_path / "app")
    database = getattr(profile.state, store)
    database.parent.mkdir(parents=True)
    files = [Path(f"{database}{suffix}") for suffix in ("", "-wal", "-shm", "-journal")]
    for path in files:
        path.write_bytes(b"private state")
        _make_public(path)

    profile.ensure()
    profile.ensure()

    for path in files:
        assert path_is_owner_restricted(path)
        assert path.read_bytes() == b"private state"


@pytest.mark.parametrize("directory", ["app_home", "state", "runtime", "workspaces"])
def test_linked_state_directories_are_refused(tmp_path: Path, directory: str) -> None:
    home = tmp_path / "app"
    outside = tmp_path / "outside"
    outside.mkdir()
    home.mkdir()
    link = home if directory == "app_home" else home / directory
    if link == home:
        home.rmdir()
    link.symlink_to(outside, target_is_directory=True)
    original_mode = outside.stat().st_mode

    with pytest.raises(DesktopProfileError, match="linked"):
        _profile(home).ensure()

    assert outside.stat().st_mode == original_mode
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_linked_database_and_side_files_are_refused(
    tmp_path: Path, suffix: str, kind: str
) -> None:
    profile = _profile(tmp_path / "app")
    database = profile.state.database_path
    database.parent.mkdir(parents=True)
    outside = tmp_path / "outside.db"
    outside.write_bytes(b"outside state")
    original_mode = outside.stat().st_mode
    link = Path(f"{database}{suffix}")
    if kind == "symlink":
        link.symlink_to(outside)
    else:
        link.hardlink_to(outside)

    with pytest.raises(DesktopProfileError, match=r"linked|hard links"):
        profile.ensure()

    assert outside.read_bytes() == b"outside state"
    assert outside.stat().st_mode == original_mode


def test_settings_store_preparation_enforces_desktop_privacy(tmp_path: Path) -> None:
    settings = Settings(project_root=tmp_path, desktop_app_home=tmp_path / "app")
    state = derive_state_paths(settings.a2a_home)

    settings.prepare_state_dir(state.database_path.parent)

    for directory in provisioned_directories(state):
        assert path_is_owner_restricted(directory)
    connection = sqlite3.connect(state.database_path)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.execute("CREATE TABLE messages (content TEXT)")
        connection.execute("INSERT INTO messages VALUES ('private conversation')")
        connection.commit()
        if os.name == "nt":
            for suffix in ("", "-wal", "-shm"):
                assert path_is_owner_restricted(Path(f"{state.database_path}{suffix}"))
        # Rechecking while SQLite holds the database and side files must work.
        settings.prepare_state_dir(state.database_path.parent)
        for suffix in ("", "-wal", "-shm"):
            assert path_is_owner_restricted(Path(f"{state.database_path}{suffix}"))
        assert connection.execute("SELECT content FROM messages").fetchone() == (
            "private conversation",
        )
    finally:
        connection.close()


def test_settings_refuses_linked_store_before_sqlite_open(tmp_path: Path) -> None:
    home = tmp_path / "app"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (home / "state").symlink_to(outside, target_is_directory=True)
    settings = Settings(project_root=tmp_path, desktop_app_home=home)

    with pytest.raises(DesktopProfileError, match="linked"):
        settings.prepare_state_dir(settings.state_layout.database_path.parent)

    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("journal_mode", ["WAL", "DELETE"])
def test_sqlite_side_file_churn_does_not_stop_private_state_preparation(
    tmp_path: Path, journal_mode: str
) -> None:
    profile = _profile(tmp_path / "app")
    profile.ensure()
    database = profile.state.database_path
    with sqlite3.connect(database) as connection:
        connection.execute(f"PRAGMA journal_mode={journal_mode}")
        connection.execute("CREATE TABLE messages (content TEXT)")
    connection.close()
    stop = Event()
    ready = Event()

    def write_messages() -> int:
        count = 0
        while not stop.is_set():
            connection = sqlite3.connect(database)
            try:
                connection.execute("INSERT INTO messages VALUES ('conversation')")
                connection.commit()
                count += 1
                ready.set()
            finally:
                connection.close()
        return count

    with ThreadPoolExecutor(max_workers=1) as executor:
        writer = executor.submit(write_messages)
        try:
            assert ready.wait(timeout=10)
            for _ in range(100):
                profile.ensure()
        finally:
            stop.set()
        count = writer.result(timeout=10)

    assert count > 0
    profile.ensure()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone() == (
            count,
        )
    connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", [initialize_fresh_stores, migrate_stores])
async def test_lifecycle_refuses_linked_state(
    tmp_path: Path, entrypoint: Callable[[Path], Awaitable[MigrationResult]]
) -> None:
    home = tmp_path / "app"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (home / "state").symlink_to(outside, target_is_directory=True)

    result = await entrypoint(home)

    assert result.status == "failed"
    assert result.failed_stage == MigrationStage.PRECONDITION
    assert result.error_class == "DesktopProfileError"
    assert result.stores == ()
    assert list(outside.iterdir()) == []


@contextmanager
def _deny_permission_changes(directory: Path) -> Generator[None]:
    """Deny WRITE_DAC, retaining a preauthorized handle for safe restoration."""
    if os.name != "nt":
        raise RuntimeError("Windows ACL testing requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    handle = kernel32.CreateFileW(
        str(directory), 0x00060000, 7, None, 3, 0x02000000, None
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    handle = ctypes.c_void_p(handle)
    original = ctypes.c_void_p()
    original_dacl = ctypes.c_void_p()
    denied = ctypes.c_void_p()
    token = ctypes.c_void_p()
    previous_privileges = ctypes.create_string_buffer(65_536)
    previous_length = ctypes.c_uint32()
    privileges_disabled = False
    try:
        # Elevated test hosts can otherwise bypass a real WRITE_DAC denial.
        if not advapi32.OpenProcessToken(
            ctypes.c_void_p(-1), 0x28, ctypes.byref(token)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not advapi32.AdjustTokenPrivileges(
            token,
            True,
            None,
            len(previous_privileges),
            previous_privileges,
            ctypes.byref(previous_length),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        privileges_disabled = True
        result = advapi32.GetSecurityInfo(
            handle,
            1,
            4,
            None,
            None,
            ctypes.byref(original_dacl),
            None,
            ctypes.byref(original),
        )
        if result:
            raise ctypes.WinError(result)
        # OWNER RIGHTS overrides the owner's implicit WRITE_DAC permission.
        sddl = f"D:P(D;;WD;;;OW)(A;;FA;;;{windows_current_user_sid()})"
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(denied), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        denied_dacl = ctypes.c_void_p()
        present = ctypes.c_int()
        defaulted = ctypes.c_int()
        if not advapi32.GetSecurityDescriptorDacl(
            denied,
            ctypes.byref(present),
            ctypes.byref(denied_dacl),
            ctypes.byref(defaulted),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        result = advapi32.SetSecurityInfo(
            handle, 1, 4 | 0x80000000, None, None, denied_dacl, None
        )
        if result:
            raise ctypes.WinError(result)
        yield
    finally:
        if original_dacl.value:
            result = advapi32.SetSecurityInfo(
                handle, 1, 4 | 0x80000000, None, None, original_dacl, None
            )
            if result:
                raise ctypes.WinError(result)
        if privileges_disabled and not advapi32.AdjustTokenPrivileges(
            token, False, previous_privileges, 0, None, None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if token.value:
            kernel32.CloseHandle(token)
        if original.value:
            kernel32.LocalFree(original)
        if denied.value:
            kernel32.LocalFree(denied)
        kernel32.CloseHandle(handle)


if os.name == "nt":

    def test_acl_failure_stops_desktop_setup(tmp_path: Path) -> None:
        profile = _profile(tmp_path / "app")
        profile.ensure()
        directory = profile.app_home

        with (
            _deny_permission_changes(directory),
            pytest.raises(DesktopProfileError, match="cannot protect") as caught,
        ):
            profile.ensure()

        assert str(directory) in str(caught.value)
        assert isinstance(caught.value.__cause__, OSError)
        profile.ensure()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("entrypoint", [initialize_fresh_stores, migrate_stores])
    async def test_acl_failure_stops_lifecycle_before_database_creation(
        tmp_path: Path, entrypoint: Callable[[Path], Awaitable[MigrationResult]]
    ) -> None:
        profile = _profile(tmp_path / "app")
        profile.ensure()

        with _deny_permission_changes(profile.app_home):
            result = await entrypoint(profile.app_home)

        assert result.status == "failed"
        assert result.failed_stage == MigrationStage.PRECONDITION
        assert result.error_class == "DesktopProfileError"
        assert not profile.state.database_path.exists()
        assert not profile.state.checkpoint_path.exists()
