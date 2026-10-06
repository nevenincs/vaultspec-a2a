"""Resolver parsing and real descriptor controls, without alternate DNS policy."""

from __future__ import annotations

import os
import sys
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

import pytest

from .._linux_helper import anonymous_data
from .._linux_resolver import (
    _alias_target,
    _directory,
    _read_snapshot,
    _resolver_owners,
    host_resolver_data,
    parse_resolver,
)


def test_resolver_preserves_order_last_search_and_ordered_options() -> None:
    parsed = parse_resolver(
        b"# private comment is not child data\n"
        b"nameserver 127.0.0.53\n"
        b"nameserver 2001:db8::1\n"
        b"domain old.example\nsearch first.example second.example\n"
        b"options ndots:2 timeout:1\noptions rotate attempts:3\n"
        b"domain selected.example\n"
    )
    assert parsed.render() == (
        b"nameserver 127.0.0.53\nnameserver 2001:db8::1\n"
        b"search selected.example\noptions ndots:2 timeout:1 rotate attempts:3\n"
    )
    assert hash(parsed) == hash(parse_resolver(parsed.render()))


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"# no selected resolver\n",
        b"nameserver host.example\n",
        b"nameserver fe80::1%eth0\n",
        b" nameserver 1.1.1.1\n",
        b"nameserver 127.0.0.53 # ambiguous\n",
        b"nameserver 127.0.0.53\x00\n",
        b"nameserver 127.0.0.53\noptions invented-option\n",
        b"nameserver 127.0.0.53\noptions timeout:31\n",
        b"nameserver 127.0.0.53\noptions attempts:0\n",
        b"nameserver 127.0.0.53\noptions ndots:016\n",
        b"nameserver 127.0.0.53\nsortlist 10.0.0.0/8\n",
        b"nameserver 127.0.0.53\nsearch ../credentials\n",
        b"nameserver 127.0.0.53\ndomain a.example b.example\n",
        b"nameserver 127.0.0.53\n" * 4,
        b"nameserver 127.0.0.53\nsearch " + b"a " * 7,
        b"nameserver 127.0.0.53\noptions " + b"rotate " * 65,
        b"#" * 16385,
        b"# long " + b"x" * 1025,
        b"#\n" * 129,
    ],
)
def test_resolver_refuses_ambiguous_unsupported_or_oversized_data(data: bytes) -> None:
    with pytest.raises(ValueError):
        parse_resolver(data)


def test_resolver_alias_policy_has_no_discovery_or_directory_redirection() -> None:
    assert _alias_target("../run/systemd/resolve/stub-resolv.conf") == PurePosixPath(
        "/run/systemd/resolve/stub-resolv.conf"
    )
    assert _alias_target("/mnt/wsl/resolv.conf") == PurePosixPath(
        "/mnt/wsl/resolv.conf"
    )
    for value in (
        "/proc/self/fd/3",
        "/etc/../mnt/wsl/resolv.conf",
        "../../mnt/wsl/resolv.conf",
        "/run/systemd/resolve/../resolve/resolv.conf",
        "/home/operator/resolv.conf",
    ):
        with pytest.raises(ValueError, match="unsupported"):
            _alias_target(value)


def test_real_host_snapshot_is_sealed_and_source_descriptors_close(
    tmp_path: Path,
) -> None:
    if sys.platform != "linux":
        with pytest.raises(ValueError, match="requires Linux"):
            host_resolver_data()
        return
    before = set(os.listdir("/proc/self/fd"))
    data = host_resolver_data()
    assert parse_resolver(data).render() == data
    assert set(os.listdir("/proc/self/fd")) == before
    snapshot = tmp_path / "snapshot"
    snapshot.write_bytes(data)
    snapshot.chmod(0o600)
    source = os.open(snapshot, os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.lseek(source, 1, os.SEEK_SET)
        with pytest.raises(ValueError, match="changed while reading"):
            _read_snapshot(source, owners=frozenset({os.geteuid()}))
    finally:
        os.close(source)
    descriptor = anonymous_data(data)
    try:
        assert os.read(descriptor, len(data) + 1) == data
        assert not os.get_inheritable(descriptor)
        with pytest.raises(OSError):
            os.write(descriptor, b"changed")
        with pytest.raises(OSError):
            os.ftruncate(descriptor, 0)
    finally:
        os.close(descriptor)


def test_real_untrusted_source_special_file_and_link_refusal(tmp_path: Path) -> None:
    if sys.platform != "linux":
        with pytest.raises(ValueError, match="requires Linux"):
            host_resolver_data()
        return
    target = tmp_path / "resolver"
    target.write_bytes(b"nameserver 127.0.0.53\n")
    link = tmp_path / "redirect"
    link.symlink_to(target)
    with pytest.raises(OSError):
        os.open(link, os.O_RDONLY | os.O_NOFOLLOW)
    target.chmod(0o666)
    descriptor = os.open(target, os.O_RDONLY)
    try:
        with pytest.raises(ValueError, match="permissions"):
            _read_snapshot(descriptor)
    finally:
        os.close(descriptor)
    target.chmod(0o644)
    os.link(target, tmp_path / "another-link")
    descriptor = os.open(target, os.O_RDONLY)
    try:
        with pytest.raises(ValueError, match="single-link"):
            _read_snapshot(descriptor)
    finally:
        os.close(descriptor)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    descriptor = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        with pytest.raises(ValueError, match="regular"):
            _read_snapshot(descriptor)
    finally:
        os.close(descriptor)
    with ExitStack() as stack, pytest.raises(ValueError, match="directory"):
        _directory(stack, PurePosixPath(str(target)))
    untrusted = tmp_path / "untrusted"
    untrusted.write_bytes(b"nameserver 127.0.0.53\n")
    untrusted.chmod(0o644)
    descriptor = os.open(untrusted, os.O_RDONLY)
    try:
        if os.geteuid() != 0:
            with pytest.raises(ValueError, match="host-owned"):
                _read_snapshot(descriptor)
    finally:
        os.close(descriptor)


def test_service_ownership_is_limited_to_fixed_resolved_aliases() -> None:
    for target in (
        "/etc/resolv.conf",
        "/run/systemd/resolv.conf",
        "/run/systemd/resolve/other.conf",
        "/run/NetworkManager/resolv.conf",
        "/mnt/wsl/resolv.conf",
    ):
        assert _resolver_owners(PurePosixPath(target)) == {0}
    if sys.platform != "linux":
        return
    import pwd

    try:
        service = pwd.getpwnam("systemd-resolve")
    except KeyError:
        assert _resolver_owners(PurePosixPath("/run/systemd/resolve/resolv.conf")) == {
            0
        }
        return
    for name in ("resolv.conf", "stub-resolv.conf"):
        target = PurePosixPath("/run/systemd/resolve") / name
        if service.pw_uid != 0 and service.pw_uid == os.geteuid():
            with pytest.raises(ValueError, match="calling identity"):
                _resolver_owners(target)
        else:
            assert _resolver_owners(target) == {0, service.pw_uid}
