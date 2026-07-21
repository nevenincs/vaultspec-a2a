from __future__ import annotations

import base64
import hashlib
import io
import tarfile
import zipfile
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.desktop.install_layout import (
    ArchiveMember,
    InstallLayoutError,
    TarballSource,
    WheelSource,
    build_acp_closure_layout,
    build_python_closure_layout,
)
from vaultspec_a2a.desktop.installed_inventory import _MAX_MEMBER_BYTES

if TYPE_CHECKING:
    from pathlib import Path

_GATEWAY_SCRIPT = ("vaultspec-a2a", "vaultspec_a2a.cli.main:main")
_MCP_SCRIPT = ("vaultspec-a2a-mcp", "vaultspec_a2a.protocols.mcp.__main__:main")
_HEX = "a" * 64


def _wheel_of(*members: ArchiveMember) -> WheelSource:
    return WheelSource(
        source_sha256=_HEX,
        distribution="example",
        version="1.0",
        members=members,
    )


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_bytes(contents: dict[str, bytes], *, record_path: str) -> bytes:
    lines = []
    for member in sorted(contents):
        encoded = (
            base64.urlsafe_b64encode(hashlib.sha256(contents[member]).digest())
            .decode("ascii")
            .rstrip("=")
        )
        lines.append(f"{member},sha256={encoded},{len(contents[member])}")
    lines.append(f"{record_path},,")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _write_wheel(path: Path, contents: dict[str, bytes]) -> None:
    record_path = "example-1.0.dist-info/RECORD"
    full = dict(contents)
    full[record_path] = _record_bytes(contents, record_path=record_path)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in sorted(full):
            archive.writestr(member, full[member])


def _members_from_zip(path: Path) -> tuple[ArchiveMember, ...]:
    members = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            data = archive.read(info.filename)
            members.append(
                ArchiveMember(
                    member=info.filename, size=len(data), sha256=_digest(data)
                )
            )
    return tuple(members)


def _write_tarball(path: Path, contents: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for member in sorted(contents):
            payload = contents[member]
            info = tarfile.TarInfo(name=member)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))


def _members_from_tar(path: Path) -> tuple[ArchiveMember, ...]:
    members = []
    with tarfile.open(path, "r:gz") as archive:
        for entry in archive.getmembers():
            if not entry.isfile():
                continue
            source = archive.extractfile(entry)
            assert source is not None
            data = source.read()
            members.append(
                ArchiveMember(member=entry.name, size=len(data), sha256=_digest(data))
            )
    return tuple(members)


def _wheel_source(path: Path, contents: dict[str, bytes]) -> WheelSource:
    _write_wheel(path, contents)
    return WheelSource(
        source_sha256=_digest(path.read_bytes()),
        distribution="example",
        version="1.0",
        members=_members_from_zip(path),
    )


def _base_wheel_contents() -> dict[str, bytes]:
    return {
        "vaultspec_a2a/cli/main.py": b"def main() -> None:\n    return None\n",
        "vaultspec_a2a/protocols/mcp/__main__.py": b"def main() -> None:\n    pass\n",
        "click/__init__.py": b"# click\n",
        "example-1.0.dist-info/METADATA": b"Name: example\nVersion: 1.0\n",
        "example-1.0.data/purelib/example/pure.py": b"PURE = 1\n",
        "example-1.0.data/platlib/example/_ext.py": b"EXT = 2\n",
    }


def test_wheel_layout_places_members_under_library_root(tmp_path: Path) -> None:
    contents = _base_wheel_contents()
    wheel = _wheel_source(tmp_path / "example-1.0-py3-none-any.whl", contents)

    layout = build_python_closure_layout(
        wheels=(wheel,),
        console_scripts=(_GATEWAY_SCRIPT, _MCP_SCRIPT),
    )

    assert layout.closure_kind == "python"
    assert layout.install_root == "runtime/python"
    by_path = {file.relative_path: file for file in layout.files}

    # Archive-root members land verbatim under the one library root.
    assert "click/__init__.py" in by_path
    assert "vaultspec_a2a/cli/main.py" in by_path
    assert "example-1.0.dist-info/METADATA" in by_path
    # .data/purelib and .data/platlib collapse to that same root.
    assert "example/pure.py" in by_path
    assert "example/_ext.py" in by_path
    assert not any(".data" in path for path in by_path)

    # size/sha256 are carried from the RECORD-verified member evidence.
    pure = by_path["example/pure.py"]
    assert pure.size == len(contents["example-1.0.data/purelib/example/pure.py"])
    assert pure.sha256 == _digest(contents["example-1.0.data/purelib/example/pure.py"])
    assert pure.source_member == "example-1.0.data/purelib/example/pure.py"
    assert pure.source_sha256 == wheel.source_sha256


def test_wheel_entrypoints_are_the_console_script_module_files(tmp_path: Path) -> None:
    contents = _base_wheel_contents()
    wheel = _wheel_source(tmp_path / "example-1.0-py3-none-any.whl", contents)

    layout = build_python_closure_layout(
        wheels=(wheel,),
        console_scripts=(_GATEWAY_SCRIPT, _MCP_SCRIPT),
    )

    assert layout.entrypoints == (
        "vaultspec_a2a/cli/main.py",
        "vaultspec_a2a/protocols/mcp/__main__.py",
    )
    by_path = {file.relative_path: file for file in layout.files}
    for entrypoint in layout.entrypoints:
        assert by_path[entrypoint].mode == "0755"
    for path, file in by_path.items():
        if path not in layout.entrypoints:
            assert file.mode == "0644"


def test_wheel_layout_is_deterministic_under_member_reordering(tmp_path: Path) -> None:
    contents = _base_wheel_contents()
    wheel = _wheel_source(tmp_path / "example-1.0-py3-none-any.whl", contents)
    shuffled = WheelSource(
        source_sha256=wheel.source_sha256,
        distribution=wheel.distribution,
        version=wheel.version,
        members=tuple(reversed(wheel.members)),
    )

    first = build_python_closure_layout(
        wheels=(wheel,), console_scripts=(_GATEWAY_SCRIPT, _MCP_SCRIPT)
    )
    second = build_python_closure_layout(
        wheels=(shuffled,), console_scripts=(_MCP_SCRIPT, _GATEWAY_SCRIPT)
    )

    assert first == second


def test_console_script_without_backing_module_fails_closed(tmp_path: Path) -> None:
    contents = _base_wheel_contents()
    del contents["vaultspec_a2a/cli/main.py"]
    wheel = _wheel_source(tmp_path / "example-1.0-py3-none-any.whl", contents)

    with pytest.raises(InstallLayoutError, match="does not name a placed module file"):
        build_python_closure_layout(
            wheels=(wheel,), console_scripts=(_GATEWAY_SCRIPT, _MCP_SCRIPT)
        )


def test_cross_wheel_path_collision_fails_closed(tmp_path: Path) -> None:
    contents = {"click/__init__.py": b"# a\n", "example-1.0.dist-info/METADATA": b"x\n"}
    first = _wheel_source(tmp_path / "a.whl", contents)
    second = _wheel_source(tmp_path / "b.whl", {"click/__init__.py": b"# b\n"})

    with pytest.raises(InstallLayoutError, match="path collision"):
        build_python_closure_layout(wheels=(first, second), console_scripts=())


@pytest.mark.parametrize(
    ("member", "match"),
    [
        ("example-1.0.data/data/share/example/data.txt", "\\.data/data"),
        ("example-1.0.data/platinclude/example/x.h", "\\.data/platinclude"),
        ("example-1.0.data/purelib", "unplaceable"),
        ("example-1.0.data/lib64/example/x.so", "\\.data key is unsupported"),
    ],
)
def test_unsupported_wheel_members_fail_closed(
    tmp_path: Path, member: str, match: str
) -> None:
    contents = {"example-1.0.dist-info/METADATA": b"Name: example\n"}
    contents[member] = b"x\n"
    wheel = _wheel_source(tmp_path / "example-1.0-py3-none-any.whl", contents)

    with pytest.raises(InstallLayoutError, match=match):
        build_python_closure_layout(wheels=(wheel,), console_scripts=())


def test_data_headers_and_scripts_are_dropped_with_evidence(tmp_path: Path) -> None:
    # A real greenlet-shaped header and jsonpointer-shaped #!python script alongside
    # importable library code: the header and script are dropped (not placed, not
    # failed) while purelib/platlib still install in full, and each drop is recorded.
    contents = {
        "example-1.0.dist-info/METADATA": b"Name: example\n",
        "example-1.0.data/purelib/example/pure.py": b"PURE = 1\n",
        "example-1.0.data/platlib/example/_ext.py": b"EXT = 2\n",
        "example-1.0.data/headers/example/greenlet.h": b"/* header */\n",
        "example-1.0.data/scripts/jsonpointer": b"#!python\nprint('cli')\n",
    }
    wheel = _wheel_source(tmp_path / "example-1.0-py3-none-any.whl", contents)

    layout = build_python_closure_layout(wheels=(wheel,), console_scripts=())

    placed = {file.relative_path for file in layout.files}
    # The importable library members still install in full.
    assert "example/pure.py" in placed
    assert "example/_ext.py" in placed
    # Nothing from headers or scripts reached the tree.
    assert not any("greenlet.h" in path for path in placed)
    assert not any("jsonpointer" in path for path in placed)

    dropped = {member.source_member: member for member in layout.dropped}
    assert dropped.keys() == {
        "example-1.0.data/headers/example/greenlet.h",
        "example-1.0.data/scripts/jsonpointer",
    }
    header = dropped["example-1.0.data/headers/example/greenlet.h"]
    assert header.reason == "data-headers"
    assert header.source_sha256 == wheel.source_sha256
    assert header.size == len(contents["example-1.0.data/headers/example/greenlet.h"])
    assert header.sha256 == _digest(
        contents["example-1.0.data/headers/example/greenlet.h"]
    )
    script = dropped["example-1.0.data/scripts/jsonpointer"]
    assert script.reason == "data-scripts"
    assert script.sha256 == _digest(contents["example-1.0.data/scripts/jsonpointer"])


def test_dropped_evidence_is_deterministic(tmp_path: Path) -> None:
    contents = {
        "example-1.0.dist-info/METADATA": b"Name: example\n",
        "example-1.0.data/purelib/example/pure.py": b"PURE = 1\n",
        "example-1.0.data/headers/example/greenlet.h": b"/* header */\n",
        "example-1.0.data/scripts/jsonpointer": b"#!python\nprint('cli')\n",
    }
    wheel = _wheel_source(tmp_path / "example-1.0-py3-none-any.whl", contents)
    shuffled = WheelSource(
        source_sha256=wheel.source_sha256,
        distribution=wheel.distribution,
        version=wheel.version,
        members=tuple(reversed(wheel.members)),
    )

    first = build_python_closure_layout(wheels=(wheel,), console_scripts=())
    second = build_python_closure_layout(wheels=(shuffled,), console_scripts=())

    assert first == second
    assert len(first.dropped) == 2


def test_acp_layout_projects_verbatim_to_install_path(tmp_path: Path) -> None:
    contents = {
        "package/package.json": b'{"name":"claude-agent-acp","version":"1.0.0"}\n',
        "package/dist/index.js": b"module.exports = {}\n",
        "package/bin/acp": b"#!/usr/bin/env node\n",
    }
    path = tmp_path / "acp.tgz"
    _write_tarball(path, contents)
    tarball = TarballSource(
        source_sha256=_digest(path.read_bytes()),
        install_path="node_modules/@agentclientprotocol/claude-agent-acp",
        members=_members_from_tar(path),
    )

    layout = build_acp_closure_layout(
        tarballs=(tarball,),
        bin_entrypoints=("node_modules/@agentclientprotocol/claude-agent-acp/bin/acp",),
    )

    assert layout.closure_kind == "acp"
    assert layout.install_root == "runtime/acp"
    by_path = {file.relative_path: file for file in layout.files}
    index = by_path["node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js"]
    assert index.mode == "0644"
    assert index.source_member == "package/dist/index.js"
    assert index.size == len(contents["package/dist/index.js"])
    assert index.sha256 == _digest(contents["package/dist/index.js"])
    bin_script = by_path["node_modules/@agentclientprotocol/claude-agent-acp/bin/acp"]
    assert bin_script.mode == "0755"
    assert layout.entrypoints == (
        "node_modules/@agentclientprotocol/claude-agent-acp/bin/acp",
    )


def test_acp_member_outside_package_root_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "acp.tgz"
    _write_tarball(path, {"package/index.js": b"x\n"})
    members = (*_members_from_tar(path), ArchiveMember("rogue.js", 2, _digest(b"x\n")))
    tarball = TarballSource(
        source_sha256=_digest(path.read_bytes()),
        install_path="node_modules/pkg",
        members=members,
    )

    with pytest.raises(InstallLayoutError, match="outside the package root"):
        build_acp_closure_layout(tarballs=(tarball,), bin_entrypoints=())


def test_acp_bin_entrypoint_must_name_a_placed_file(tmp_path: Path) -> None:
    path = tmp_path / "acp.tgz"
    _write_tarball(path, {"package/index.js": b"x\n"})
    tarball = TarballSource(
        source_sha256=_digest(path.read_bytes()),
        install_path="node_modules/pkg",
        members=_members_from_tar(path),
    )

    with pytest.raises(InstallLayoutError, match="does not name a placed file"):
        build_acp_closure_layout(
            tarballs=(tarball,),
            bin_entrypoints=("node_modules/pkg/bin/missing",),
        )


def test_non_ascii_destination_fails_closed() -> None:
    # café clears the looser archive-member validator but the strict dashboard
    # grammar rejects it; the reused validator's ValueError must surface as the
    # module's named error rather than escaping untyped.
    wheel = _wheel_of(ArchiveMember(member="café/x.py", size=1, sha256=_HEX))

    with pytest.raises(InstallLayoutError, match="portable dashboard path"):
        build_python_closure_layout(wheels=(wheel,), console_scripts=())


def test_member_size_over_bound_fails_closed() -> None:
    wheel = _wheel_of(
        ArchiveMember(member="a.py", size=_MAX_MEMBER_BYTES + 1, sha256=_HEX)
    )

    with pytest.raises(InstallLayoutError, match="member size is out of bounds"):
        build_python_closure_layout(wheels=(wheel,), console_scripts=())


def test_member_bad_digest_fails_closed() -> None:
    wheel = _wheel_of(ArchiveMember(member="a.py", size=1, sha256="not-a-digest"))

    with pytest.raises(InstallLayoutError, match="member digest is invalid"):
        build_python_closure_layout(wheels=(wheel,), console_scripts=())


def test_non_portable_member_fails_closed() -> None:
    wheel = _wheel_of(ArchiveMember(member="../escape.py", size=1, sha256=_HEX))

    with pytest.raises(InstallLayoutError, match="member path is not portable"):
        build_python_closure_layout(wheels=(wheel,), console_scripts=())


def test_console_reference_without_attribute_fails_closed() -> None:
    wheel = _wheel_of(
        ArchiveMember(member="vaultspec_a2a/cli/main.py", size=1, sha256=_HEX)
    )

    with pytest.raises(InstallLayoutError, match="reference is malformed"):
        build_python_closure_layout(
            wheels=(wheel,), console_scripts=(("x", "no_colon_here"),)
        )


def test_console_reference_with_empty_module_part_fails_closed() -> None:
    wheel = _wheel_of(
        ArchiveMember(member="vaultspec_a2a/cli/main.py", size=1, sha256=_HEX)
    )

    with pytest.raises(InstallLayoutError, match="module path is malformed"):
        build_python_closure_layout(
            wheels=(wheel,), console_scripts=(("x", "a..b:main"),)
        )


def test_empty_closure_must_place_a_file() -> None:
    with pytest.raises(InstallLayoutError, match="must place at least one file"):
        build_python_closure_layout(wheels=(_wheel_of(),), console_scripts=())
