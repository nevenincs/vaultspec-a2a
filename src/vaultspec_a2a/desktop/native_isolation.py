"""Worker-owned filesystem grants and the capsule's Linux isolation closure."""

from __future__ import annotations

import base64
import errno
import hashlib
import json
import os
import re
import stat
import sys
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..utils.process import ProcessContainmentError
from ..utils.runtime_exec import is_frozen, module_command
from ..workspace.environment import scrub_infrastructure_environment
from ._filesystem_authority import (
    DirectoryAuthority,
    assert_directory_authority,
    confined_file_descriptor,
    directory_lease,
    resolve_directory_authority,
)
from ._linux_helper import anonymous_arguments, require_static_helper
from .profile import derive_state_paths

if TYPE_CHECKING:
    from collections.abc import Mapping

_MANIFEST = "isolation/runtime.json"
_MAX_METADATA_BYTES = 64 * 1024
_MAX_ENVIRONMENT_BYTES = 512 * 1024
_ENVIRONMENT_PREFIX = "VAULTSPEC_A2A_NATIVE_PACKET_"
_PACKET_CHUNK_BYTES = 32768
_MAX_PACKET_CHUNKS = 22


class _StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _RootRecord(_StrictRecord):
    path: str
    device: int
    inode: int

    def authority(self) -> DirectoryAuthority:
        path = Path(self.path)
        if not path.is_absolute() or "\0" in self.path:
            raise ValueError("native authority requires an absolute directory")
        if path.resolve(strict=True) != path:
            raise ValueError("native authority requires a canonical directory")
        return DirectoryAuthority(path=path, identity=(self.device, self.inode))


class _LaunchRecord(_StrictRecord):
    app_home: _RootRecord
    capsule: _RootRecord
    workspace: _RootRecord
    home: _RootRecord


class _EnvironmentRecord(_StrictRecord):
    values: dict[str, str] = Field(max_length=2048)


class RuntimeFile(_StrictRecord):
    """One capsule-relative file attested by the build-owned manifest."""

    source: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class RuntimeMount(RuntimeFile):
    """A runtime file copied into the closure at build time."""

    target: str


class LinuxRuntimeClosure(_StrictRecord):
    """Pinned native helper and runtime files, never host-discovered at launch."""

    schema_version: Literal[1]
    helper_version: Literal["0.11.1"]
    helper: RuntimeFile
    files: list[RuntimeMount] = Field(max_length=128)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate native authority field")
        result[key] = value
    return result


def _decode_record(value: str) -> object:
    if len(value.encode("utf-8")) > _MAX_METADATA_BYTES:
        raise ValueError("native authority metadata exceeds its bound")
    try:
        return json.loads(value, object_pairs_hook=_unique_object)
    except RecursionError as exc:
        raise ValueError("native authority metadata is too deeply nested") from exc


@dataclass(frozen=True, slots=True)
class NativeWorkspaceAuthority:
    """Capture the trusted worker's project and runtime before role preparation."""

    app_home: DirectoryAuthority
    capsule: DirectoryAuthority
    workspace: DirectoryAuthority

    @classmethod
    def issue(
        cls, *, app_home: Path, capsule: Path, workspace: Path
    ) -> NativeWorkspaceAuthority:
        authority = cls(
            app_home=resolve_directory_authority(app_home),
            capsule=resolve_directory_authority(capsule),
            workspace=resolve_directory_authority(workspace),
        )
        authority.validate()
        return authority

    def validate(self) -> None:
        """Keep captured identities and the managed project boundary authoritative."""
        for root in (self.app_home, self.capsule, self.workspace):
            assert_directory_authority(root)
        state = derive_state_paths(self.app_home.path)
        for root in (state.workspaces_root, state.temp_homes_dir):
            if resolve_directory_authority(root).path != root:
                raise ValueError("native managed roots must not redirect")
        if not self.workspace.path.is_relative_to(state.workspaces_root):
            raise ValueError("native workspace is outside the managed tree")
        if self.capsule.path.is_relative_to(self.app_home.path) or (
            self.app_home.path.is_relative_to(self.capsule.path)
        ):
            raise ValueError("native runtime and mutable state must be separate")

    def for_home(self, home: Path) -> NativeLaunchAuthority:
        """Add exactly one prepared home without recapturing the selected roots."""
        authority = NativeLaunchAuthority(
            self.app_home,
            self.capsule,
            self.workspace,
            resolve_directory_authority(home),
        )
        authority.validate()
        return authority


@dataclass(frozen=True, slots=True)
class NativeLaunchAuthority:
    """The selected project, role home and runtime, bound to directory identities.

    The app home is a validation anchor and is never a child filesystem grant.
    Issue this in trusted worker code after workspace and auth preparation.
    """

    app_home: DirectoryAuthority
    capsule: DirectoryAuthority
    workspace: DirectoryAuthority
    home: DirectoryAuthority

    @classmethod
    def issue(
        cls, *, app_home: Path, capsule: Path, workspace: Path, home: Path
    ) -> NativeLaunchAuthority:
        return NativeWorkspaceAuthority.issue(
            app_home=app_home, capsule=capsule, workspace=workspace
        ).for_home(home)

    def validate(self) -> None:
        """Refuse changed identities, redirected roots and grants to other planes."""
        NativeWorkspaceAuthority(self.app_home, self.capsule, self.workspace).validate()
        assert_directory_authority(self.home)
        homes = derive_state_paths(self.app_home.path).temp_homes_dir
        if self.home.path == homes or not self.home.path.is_relative_to(homes):
            raise ValueError("native auth home must be one selected role home")

    def canonical_cwd(self, value: str) -> str:
        path = Path(value).resolve(strict=True)
        if not path.is_dir() or not any(
            path.is_relative_to(root.path)
            for root in (self.workspace, self.home, self.capsule)
        ):
            raise ValueError("native cwd is outside this launch's grants")
        return str(path)

    def encode(self) -> str:
        def root(value: DirectoryAuthority) -> _RootRecord:
            return _RootRecord(
                path=str(value.path), device=value.identity[0], inode=value.identity[1]
            )

        return _LaunchRecord(
            app_home=root(self.app_home),
            capsule=root(self.capsule),
            workspace=root(self.workspace),
            home=root(self.home),
        ).model_dump_json()

    @classmethod
    def decode(cls, value: str) -> NativeLaunchAuthority:
        record = _LaunchRecord.model_validate(_decode_record(value))
        authority = cls(
            app_home=record.app_home.authority(),
            capsule=record.capsule.authority(),
            workspace=record.workspace.authority(),
            home=record.home.authority(),
        )
        authority.validate()
        return authority


def _validate_environment(environment: Mapping[str, str]) -> None:
    for name, value in environment.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError("native environment requires valid variable names")
        if "\0" in value or len(value.encode("utf-8")) > 65536:
            raise ValueError("native environment value is invalid or too large")


def _validate_command(command: list[str]) -> None:
    if not command or len(command) > 512 or any("\0" in arg for arg in command):
        raise ValueError("native launch requires a bounded command without NULs")


def _bootstrap_environment() -> dict[str, str]:
    # Never inherit role-controlled loader hooks, Python paths or startup homes.
    environment = {"LANG": "C.UTF-8"}
    if is_frozen():
        bundle = getattr(sys, "_MEIPASS", None)
        if not isinstance(bundle, str):
            raise ProcessContainmentError("frozen native launcher lacks its bundle")
        environment["LD_LIBRARY_PATH"] = str(Path(bundle).resolve(strict=True))
    return environment


def decode_launch_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Decode opaque role data after the trusted interpreter has started."""
    count = environment.get(_ENVIRONMENT_PREFIX + "COUNT", "")
    if not re.fullmatch(r"[1-9][0-9]?", count) or int(count) > _MAX_PACKET_CHUNKS:
        raise ValueError("native environment packet has an invalid chunk count")
    pieces: list[str] = []
    for index in range(int(count)):
        value = environment.get(_ENVIRONMENT_PREFIX + str(index))
        if value is None or len(value) > _PACKET_CHUNK_BYTES:
            raise ValueError("native environment packet is incomplete or oversized")
        pieces.append(value)
    raw = base64.b64decode("".join(pieces), validate=True)
    if len(raw) > _MAX_ENVIRONMENT_BYTES:
        raise ValueError("native environment packet exceeds its bound")
    try:
        parsed = json.loads(raw, object_pairs_hook=_unique_object)
    except RecursionError as exc:
        raise ValueError("native environment packet is too deeply nested") from exc
    record = _EnvironmentRecord.model_validate(parsed)
    _validate_environment(record.values)
    return record.values


@dataclass(frozen=True, slots=True)
class NativeLaunch:
    """An inseparable trusted bootstrap command, environment and working directory."""

    command: tuple[str, ...]
    environment: Mapping[str, str] = field(repr=False)
    cwd: str


def linux_isolated_launch(
    authority: NativeLaunchAuthority,
    command: list[str],
    *,
    cwd: str,
    environment: Mapping[str, str],
) -> NativeLaunch:
    """Render a clean bootstrap; this alone never grants served eligibility."""
    if sys.platform != "linux":
        raise ProcessContainmentError("native namespace isolation requires Linux")
    authority.validate()
    _validate_command(command)
    _validate_environment(environment)
    raw = _EnvironmentRecord(values=dict(environment)).model_dump_json().encode("utf-8")
    if len(raw) > _MAX_ENVIRONMENT_BYTES:
        raise ValueError("native environment packet exceeds its bound")
    encoded = base64.b64encode(raw).decode("ascii")
    chunks = [
        encoded[offset : offset + _PACKET_CHUNK_BYTES]
        for offset in range(0, len(encoded), _PACKET_CHUNK_BYTES)
    ]
    bootstrap_env = _bootstrap_environment()
    bootstrap_env[_ENVIRONMENT_PREFIX + "COUNT"] = str(len(chunks))
    bootstrap_env.update(
        (_ENVIRONMENT_PREFIX + str(index), chunk) for index, chunk in enumerate(chunks)
    )
    argv = module_command(
        "vaultspec_a2a.desktop._linux_launcher",
        authority.encode(),
        authority.canonical_cwd(cwd),
        *command,
        isolated=True,
    )
    return NativeLaunch(
        command=tuple(argv),
        environment=MappingProxyType(bootstrap_env),
        cwd=str(authority.capsule.path),
    )


def _relative_source(value: str) -> str:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or "\0" in value
        or "\\" in value
    ):
        raise ValueError("runtime source must be a canonical capsule-relative file")
    return value


def _runtime_target(value: str, authority: NativeLaunchAuthority) -> str:
    path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or path.as_posix() != value
        or path == PurePosixPath("/")
        or any(part in {"", ".", ".."} for part in value.split("/")[1:])
        or "\0" in value
        or "\\" in value
    ):
        raise ValueError("runtime target must be a canonical absolute file")
    protected = (
        Path("/proc"),
        Path("/dev"),
        Path("/tmp"),
        authority.app_home.path,
        authority.capsule.path,
    )
    if any(Path(value).is_relative_to(root) for root in protected):
        raise ValueError("runtime mapping overlaps a protected authority")
    return value


def _capsule_file(stack: ExitStack, capsule: DirectoryAuthority, name: str) -> int:
    return stack.enter_context(
        confined_file_descriptor(
            capsule.path,
            tuple(_relative_source(name).split("/")),
            expected_root_identity=capsule.identity,
        )
    )


def _attested_file(
    stack: ExitStack, capsule: DirectoryAuthority, record: RuntimeFile
) -> int:
    descriptor = _capsule_file(stack, capsule, record.source)
    digest = hashlib.sha256()
    while block := os.read(descriptor, 1024 * 1024):
        digest.update(block)
    if digest.hexdigest() != record.sha256:
        raise ValueError("native runtime file differs from its pinned closure")
    os.lseek(descriptor, 0, os.SEEK_SET)
    return descriptor


def exec_linux_isolated(
    authority: NativeLaunchAuthority,
    command: list[str],
    *,
    cwd: str,
    environment: Mapping[str, str],
) -> None:
    """Replace the trusted launcher with the pinned helper, with bounded FD grants."""
    if sys.platform != "linux":
        raise ProcessContainmentError("native namespace isolation requires Linux")
    authority.validate()
    selected_cwd = authority.canonical_cwd(cwd)
    _validate_command(command)
    _validate_environment(environment)
    with ExitStack() as stack:
        # Recheck leased identities before any mount. Only the three grants are
        # inherited; the validation anchor and all unrelated FDs stay closed.
        roots = [
            stack.enter_context(directory_lease(root))
            for root in (authority.capsule, authority.workspace, authority.home)
        ]
        manifest_fd = _capsule_file(stack, authority.capsule, _MANIFEST)
        metadata = os.read(manifest_fd, _MAX_METADATA_BYTES + 1)
        if len(metadata) > _MAX_METADATA_BYTES:
            raise ValueError("native runtime manifest exceeds its bound")
        closure = LinuxRuntimeClosure.model_validate(
            _decode_record(metadata.decode("utf-8"))
        )
        helper_fd = _attested_file(stack, authority.capsule, closure.helper)
        require_static_helper(helper_fd)
        helper_mode = os.fstat(helper_fd).st_mode
        if helper_mode & (stat.S_ISUID | stat.S_ISGID):
            raise ValueError("native helper cannot have privileged mode bits")
        os.lseek(helper_fd, 0, os.SEEK_SET)
        argv = [
            "bubblewrap",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--unshare-cgroup",
            "--disable-userns",
            "--cap-drop",
            "ALL",
            "--die-with-parent",
            "--new-session",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
        ]
        grant_fds: list[int] = []
        for index, root in enumerate(roots):
            if root.dir_fd is None:
                raise ProcessContainmentError("native grant lacks an opened directory")
            grant_fds.append(root.dir_fd)
            argv.extend(
                [
                    "--ro-bind-fd" if index == 0 else "--bind-fd",
                    str(root.dir_fd),
                    str(root.path),
                ]
            )
        targets: set[str] = set()
        for record in closure.files:
            target = _runtime_target(record.target, authority)
            if target in targets:
                raise ValueError("native runtime targets must be unique")
            targets.add(target)
            descriptor = _attested_file(stack, authority.capsule, record)
            grant_fds.append(descriptor)
            argv.extend(["--ro-bind-fd", str(descriptor), target])
        for descriptor in grant_fds:
            os.set_inheritable(descriptor, True)
        # bubblewrap consumes and closes every bind FD before target exec. The
        # helper FD is CLOEXEC, so the target retains only its protocol stdio.
        env = scrub_infrastructure_environment(environment)
        # Desktop authoring carries a run actor through its worker-owned relay.
        # The direct-engine bearer/journal channels never enter this role.
        relay_names = frozenset(
            "VAULTSPEC_A2A_AUTHORING_" + suffix
            for suffix in (
                "ACTOR_TOKEN",
                "RELAY_URL",
                "RUN_ID",
                "CALL_SCOPE",
                "CALL_ID_SOURCE",
                "SERVER_NAME",
                "CATALOG_JSON",
            )
        )
        env.update(
            (name, value)
            for name, value in environment.items()
            if name.upper() in relay_names
        )
        env.update(
            HOME=str(authority.home.path),
            XDG_CONFIG_HOME=str(authority.home.path / ".config"),
            XDG_CACHE_HOME=str(authority.home.path / ".cache"),
            XDG_DATA_HOME=str(authority.home.path / ".local" / "share"),
            TMPDIR="/tmp",
        )
        argv.append("--clearenv")
        for name, value in env.items():
            argv.extend(["--setenv", name, value])
        argv.extend(["--chdir", selected_cwd])
        # Credentials and role hooks are data for post-isolation target exec;
        # they must never become the host helper's loader environment or argv.
        args_fd = anonymous_arguments(argv[1:])
        stack.callback(os.close, args_fd)
        grant_fds.append(args_fd)
        os.set_inheritable(args_fd, True)
        for value in os.listdir("/proc/self/fd"):
            descriptor = int(value)
            if descriptor <= 2 or descriptor in grant_fds:
                continue
            try:
                os.set_inheritable(descriptor, False)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise
        os.execve(
            helper_fd,
            ["bubblewrap", "--args", str(args_fd), "--", *command],
            {"LANG": "C.UTF-8"},
        )
