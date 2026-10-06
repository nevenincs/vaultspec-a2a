"""Bounded host-selected DNS data for an otherwise empty Linux filesystem."""

from __future__ import annotations

import ipaddress
import os
import re
import stat
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import PurePosixPath

RESOLVER_TARGET = PurePosixPath("/etc/resolv.conf")
_MAX_BYTES = 16384
_ROOT_OWNER = frozenset({0})
_RESOLVED_ALIASES = frozenset(
    {
        "/run/systemd/resolve/stub-resolv.conf",
        "/run/systemd/resolve/resolv.conf",
    }
)
_ALIASES = frozenset(
    {
        *_RESOLVED_ALIASES,
        "/usr/lib/systemd/resolv.conf",
        "/run/NetworkManager/resolv.conf",
        "/mnt/wsl/resolv.conf",
    }
)
_FLAGS = frozenset(
    {
        "rotate",
        "edns0",
        "trust-ad",
        "single-request",
        "single-request-reopen",
        "use-vc",
        "no-tld-query",
        "no-reload",
        "no-aaaa",
    }
)
_NUMERIC_OPTIONS = {"ndots": (0, 15), "timeout": (1, 30), "attempts": (1, 5)}


@dataclass(frozen=True, slots=True)
class ResolverData:
    nameservers: tuple[str, ...]
    search: tuple[str, ...]
    options: tuple[str, ...]

    def render(self) -> bytes:
        lines = ["nameserver " + value for value in self.nameservers]
        if self.search:
            lines.append("search " + " ".join(self.search))
        if self.options:
            lines.append("options " + " ".join(self.options))
        return ("\n".join(lines) + "\n").encode("ascii")


def _domain(value: str) -> str:
    if value == ".":
        return value
    if len(value) > 253 or not all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in value.removesuffix(".").split(".")
    ):
        raise ValueError("native resolver search domain is unsupported")
    return value


def _option(value: str) -> str:
    if value in _FLAGS:
        return value
    name, separator, number = value.partition(":")
    bounds = _NUMERIC_OPTIONS.get(name)
    if (
        not separator
        or bounds is None
        or not re.fullmatch(r"0|[1-9][0-9]?", number)
        or not bounds[0] <= int(number) <= bounds[1]
    ):
        raise ValueError("native resolver option is unsupported")
    return value


def parse_resolver(data: bytes) -> ResolverData:
    """Refuse ambiguous/unsupported settings rather than silently changing DNS."""
    if len(data) > _MAX_BYTES:
        raise ValueError("native resolver data exceeds its bound")
    data = data.replace(b"\r\n", b"\n")
    if any(value not in {9, 10} and not 32 <= value <= 126 for value in data):
        raise ValueError("native resolver data contains unsupported characters")
    lines = data.decode("ascii").splitlines()
    if len(lines) > 128 or any(len(line) > 1024 for line in lines):
        raise ValueError("native resolver lines exceed their bound")
    nameservers: list[str] = []
    search: tuple[str, ...] = ()
    options: list[str] = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith(("#", ";")):
            continue
        # glibc does not activate indented directives. Canonicalization must
        # not turn an ignored line into an active setting for another runtime.
        if line[0].isspace() or "#" in line or ";" in line:
            raise ValueError("native resolver directive has ambiguous syntax")
        key, *values = line.split()
        if key == "nameserver" and len(values) == 1 and "%" not in values[0]:
            nameservers.append(str(ipaddress.ip_address(values[0])))
        elif key in {"domain", "search"} and values:
            if (key == "domain" and len(values) != 1) or len(values) > 6:
                raise ValueError("native resolver search list exceeds its bound")
            search = tuple(_domain(value) for value in values)
            if len(" ".join(search)) > 256:
                raise ValueError("native resolver search list exceeds its bound")
        elif key == "options" and values:
            options.extend(_option(value) for value in values)
        else:
            raise ValueError("native resolver directive is unsupported")
        if len(nameservers) > 3 or len(options) > 64:
            raise ValueError("native resolver settings exceed their bound")
    if not nameservers:
        raise ValueError("native resolver requires an explicit nameserver")
    return ResolverData(tuple(nameservers), search, tuple(options))


def _resolver_owners(target: PurePosixPath) -> frozenset[int]:
    if sys.platform != "linux" or str(target) not in _RESOLVED_ALIASES:
        return _ROOT_OWNER
    import pwd

    try:
        owner = pwd.getpwnam("systemd-resolve").pw_uid
    except KeyError:
        return _ROOT_OWNER
    # This service account owns only its fixed runtime directory and DNS files.
    # A caller running as that account cannot establish an independent owner.
    if owner != 0 and owner == os.geteuid():
        raise ValueError("native resolver service owner is the calling identity")
    return _ROOT_OWNER | {owner}


def _trusted_directory(
    metadata: os.stat_result,
    *,
    sticky_alias: bool,
    owners: frozenset[int] = _ROOT_OWNER,
) -> None:
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid not in owners:
        raise ValueError("native resolver directory is not host-owned")
    if metadata.st_mode & 0o022 and not (
        sticky_alias and metadata.st_mode & stat.S_ISVTX
    ):
        raise ValueError("native resolver directory is writable by other identities")


def _directory(stack: ExitStack, target: PurePosixPath) -> int:
    if sys.platform != "linux":
        raise ValueError("host resolver acquisition requires Linux")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    stack.callback(os.close, descriptor)
    _trusted_directory(os.fstat(descriptor), sticky_alias=False)
    parent = PurePosixPath("/")
    for part in target.parts[1:-1]:
        descriptor = os.open(part, flags, dir_fd=descriptor)
        stack.callback(os.close, descriptor)
        parent /= part
        _trusted_directory(
            os.fstat(descriptor),
            owners=(
                _resolver_owners(target)
                if str(parent) == "/run/systemd/resolve"
                else _ROOT_OWNER
            ),
            sticky_alias=(
                str(target) == "/mnt/wsl/resolv.conf" and str(parent) == "/mnt/wsl"
            ),
        )
    return descriptor


def _alias_target(value: str) -> PurePosixPath:
    for target in _ALIASES:
        if value in {target, ".." + target}:
            return PurePosixPath(target)
    raise ValueError("native resolver source alias is unsupported")


def _signature(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_snapshot(descriptor: int, *, owners: frozenset[int] = _ROOT_OWNER) -> bytes:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("native resolver requires a regular single-link source")
    if before.st_mode & (0o022 | stat.S_ISUID | stat.S_ISGID):
        raise ValueError("native resolver source has unsafe permissions")
    if before.st_uid not in owners:
        raise ValueError("native resolver source is not host-owned")
    if not 0 < before.st_size <= _MAX_BYTES:
        raise ValueError("native resolver source size exceeds its bound")
    chunks: list[bytes] = []
    total = 0
    while block := os.read(descriptor, min(4096, _MAX_BYTES + 1 - total)):
        chunks.append(block)
        total += len(block)
        if total > _MAX_BYTES:
            raise ValueError("native resolver source exceeds its bound")
    if (
        _signature(before) != _signature(os.fstat(descriptor))
        or total != before.st_size
    ):
        raise ValueError("native resolver source changed while reading")
    return b"".join(chunks)


def host_resolver_data() -> bytes:
    """Acquire only the fixed host resolver; no launch input selects its source."""
    if sys.platform != "linux":
        raise ValueError("host resolver acquisition requires Linux")
    with ExitStack() as stack:
        parent = _directory(stack, RESOLVER_TARGET)
        metadata = os.stat(RESOLVER_TARGET.name, dir_fd=parent, follow_symlinks=False)
        target = RESOLVER_TARGET
        if stat.S_ISLNK(metadata.st_mode):
            if metadata.st_uid != 0 or metadata.st_nlink != 1 or metadata.st_size > 256:
                raise ValueError("native resolver alias is not trusted")
            target = _alias_target(os.readlink(RESOLVER_TARGET.name, dir_fd=parent))
            if _signature(metadata) != _signature(
                os.stat(RESOLVER_TARGET.name, dir_fd=parent, follow_symlinks=False)
            ):
                raise ValueError("native resolver alias changed while reading")
            parent = _directory(stack, target)
        leaf = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
        descriptor = os.open(
            target.name,
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent,
        )
        stack.callback(os.close, descriptor)
        if _signature(leaf) != _signature(os.fstat(descriptor)):
            raise ValueError("native resolver source changed before acquisition")
        data = _read_snapshot(descriptor, owners=_resolver_owners(target))
        if _signature(leaf) != _signature(
            os.stat(target.name, dir_fd=parent, follow_symlinks=False)
        ) or _signature(metadata) != _signature(
            os.stat(
                RESOLVER_TARGET.name,
                dir_fd=_directory(stack, RESOLVER_TARGET),
                follow_symlinks=False,
            )
        ):
            raise ValueError("native resolver source changed during acquisition")
        return parse_resolver(data).render()
