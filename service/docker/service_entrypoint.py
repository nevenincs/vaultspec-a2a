"""Prepare explicit Compose state permissions, then exec the service command."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

_DATA_ROOT = Path("/app/data")


def _agent_gid() -> int:
    raw = os.environ.get("VAULTSPEC_PROVIDER_AGENT_GID")
    if raw is None:
        raise RuntimeError("VAULTSPEC_PROVIDER_AGENT_GID is required in the worker")
    gid = int(raw)
    if gid < 1:
        raise RuntimeError("VAULTSPEC_PROVIDER_AGENT_GID must be positive")
    return gid


def _owned_directory(path: Path, mode: int) -> None:
    """Create or tighten one service-owned directory without following links."""
    path.mkdir(parents=True, exist_ok=True)
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"service state path is not a real directory: {path}")
    if metadata.st_uid != _service_uid():
        raise RuntimeError(f"service state path has unexpected owner: {path}")
    os.chmod(path, mode, follow_symlinks=False)


def _shared_mode(mode: int, *, directory: bool) -> int:
    """Mirror owner access to the shared group while preserving other bits."""
    shared = (mode & ~0o070) | ((mode & 0o700) >> 3)
    return shared | (stat.S_ISGID if directory else 0)


def _required_posix(name: str) -> Any:
    value = getattr(os, name, None)
    if value is None:
        raise RuntimeError(f"service entrypoint requires os.{name}")
    return value


def _service_uid() -> int:
    """Return the service UID, failing closed when POSIX identity is unavailable."""
    getuid = getattr(os, "getuid", None)
    if not callable(getuid):
        raise RuntimeError("service entrypoint requires POSIX os.getuid")
    uid = getuid()
    if not isinstance(uid, int):
        raise RuntimeError("service entrypoint received an invalid service UID")
    return uid


def _migrate_managed_workspace(path: Path, agent_gid: int) -> None:
    """Upgrade one explicitly managed named-volume tree without following links."""
    service_uid = Path("/proc/self").stat().st_uid
    allowed_owners = {service_uid, int(os.environ["VAULTSPEC_PROVIDER_AGENT_UID"])}
    for directory, names, files, directory_fd in _required_posix("fwalk")(
        path, topdown=True, follow_symlinks=False
    ):
        directory_metadata = os.fstat(directory_fd)
        if directory_metadata.st_uid not in allowed_owners:
            raise RuntimeError(
                f"managed workspace has unsupported owner at {directory}; "
                "prepare custom mounts for the agent UID/GID and disable "
                "managed migration"
            )
        _required_posix("fchown")(directory_fd, -1, agent_gid)
        os.fchmod(
            directory_fd,
            _shared_mode(stat.S_IMODE(directory_metadata.st_mode), directory=True),
        )

        names[:] = [
            name
            for name in names
            if not stat.S_ISLNK(
                os.stat(name, dir_fd=directory_fd, follow_symlinks=False).st_mode
            )
        ]
        for name in files:
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(
                    f"managed workspace contains a special file: {directory}/{name}"
                )
            if metadata.st_nlink != 1:
                raise RuntimeError(
                    f"managed workspace contains a hard-linked file: {directory}/{name}"
                )
            if metadata.st_uid not in allowed_owners:
                raise RuntimeError(
                    f"managed workspace has unsupported owner at {directory}/{name}"
                )
            flags = os.O_RDONLY
            for flag in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
                flags |= _required_posix(flag)
            file_fd = os.open(name, flags, dir_fd=directory_fd)
            try:
                opened = os.fstat(file_fd)
                if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                    raise RuntimeError(
                        "managed workspace changed during migration: "
                        f"{directory}/{name}"
                    )
                _required_posix("fchown")(file_fd, -1, agent_gid)
                os.fchmod(
                    file_fd,
                    _shared_mode(stat.S_IMODE(opened.st_mode), directory=False),
                )
            finally:
                os.close(file_fd)


def _validate_prepared_workspace(path: Path, agent_gid: int) -> None:
    """Refuse an operator mount whose root cannot be shared by both identities."""
    metadata = path.lstat()
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_gid != agent_gid
        or mode & 0o070 != 0o070
    ):
        raise RuntimeError(
            "custom workspace mount must be a real directory prepared with the "
            "configured agent GID and group rwx access"
        )


def _workspace_directory(path: Path) -> None:
    """Upgrade a managed volume or validate an operator-prepared workspace."""
    canonical_parent = path.parent.resolve(strict=True)
    if not canonical_parent.is_relative_to(_DATA_ROOT):
        raise RuntimeError("Compose workspace root must remain beneath /app/data")
    agent_gid = _agent_gid()
    managed = os.environ.get("VAULTSPEC_MANAGED_WORKSPACE_PERMISSIONS") == "true"
    if managed:
        _owned_directory(path, 0o2770)
        _migrate_managed_workspace(path, agent_gid)
    else:
        _validate_prepared_workspace(path, agent_gid)


def _sqlite_path(environment_name: str) -> Path | None:
    raw = os.environ.get(environment_name)
    if not raw:
        return None
    parsed = make_url(raw)
    if parsed.get_backend_name() != "sqlite":
        return None
    database = parsed.database
    if not database:
        raise RuntimeError(f"{environment_name} names no SQLite database")
    path = Path(database)
    if not path.is_absolute() or not path.parent.resolve(strict=True).is_relative_to(
        _DATA_ROOT
    ):
        raise RuntimeError(f"{environment_name} must name SQLite state under /app/data")
    return path


def _tighten_sqlite_state(path: Path) -> None:
    """Repair one existing database and its explicit SQLite sidecars."""
    for candidate in (
        path,
        Path(f"{path}-wal"),
        Path(f"{path}-shm"),
        Path(f"{path}-journal"),
    ):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"SQLite state is not a regular file: {candidate}")
        if metadata.st_uid != _service_uid():
            raise RuntimeError(f"SQLite state has unexpected owner: {candidate}")
        os.chmod(candidate, 0o600, follow_symlinks=False)


def main() -> None:
    if len(sys.argv) < 2:
        raise RuntimeError("service entrypoint requires a command")
    os.umask(0o077)
    _owned_directory(_DATA_ROOT, 0o711)

    if os.environ.get("VAULTSPEC_PROVIDER_IDENTITY_LAUNCHER"):
        workspace = Path(os.environ["VAULTSPEC_WORKSPACE_ROOT"])
        _workspace_directory(workspace)

    a2a_home = Path(os.environ["VAULTSPEC_A2A_HOME"])
    if not a2a_home.is_absolute() or not a2a_home.parent.resolve(
        strict=True
    ).is_relative_to(Path("/app")):
        raise RuntimeError("VAULTSPEC_A2A_HOME must name service state beneath /app")
    _owned_directory(a2a_home, 0o700)

    for environment_name in (
        "VAULTSPEC_DATABASE_URL",
        "VAULTSPEC_CHECKPOINT_DATABASE_URL",
    ):
        database = _sqlite_path(environment_name)
        if database is not None:
            _tighten_sqlite_state(database)

    os.execvpe(sys.argv[1], sys.argv[1:], os.environ)


if __name__ == "__main__":
    main()
