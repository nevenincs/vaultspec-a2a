"""The static-ELF and privileged-mode-bits refusals, over real file content.

Platform-independent: the parser reads raw bytes through ``os.read``/``os.fstat``
and never execs anything, so every refusal below is proven on whatever host
runs the suite - the Linux-only end-to-end launch refusal (a real ``chmod u+s``
helper refused through ``linux_isolated_launch``) lives beside the other
Linux-only native-isolation certifications in ``test_native_isolation.py``.
"""

from __future__ import annotations

import os
import struct
from typing import TYPE_CHECKING

import pytest

from .._linux_helper import require_unprivileged_static_helper

if TYPE_CHECKING:
    from pathlib import Path

#: One Elf64_Phdr entry: p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz,
#: p_memsz, p_align. PT_LOAD (1) so a well-formed fixture is not itself refused
#: as carrying a dynamic dependency (PT_DYNAMIC=2, PT_INTERP=3).
_PT_LOAD = 1
_PHENTSIZE = 56
_EHSIZE = 64


def _elf64_header(
    *,
    e_type: int = 2,
    e_phoff: int = _EHSIZE,
    e_phentsize: int = _PHENTSIZE,
    e_phnum: int = 1,
) -> bytes:
    """A real little-endian ELF64 ``Ehdr``, byte-for-byte at its standard offsets."""
    ident = bytes([0x7F, 0x45, 0x4C, 0x46, 2, 1, 1, 0]) + bytes(8)
    assert len(ident) == 16
    rest = struct.pack(
        "<HHIQQQIHHHHHH",
        e_type,  # e_type (ET_EXEC=2 unless overridden)
        0x3E,  # e_machine (EM_X86_64, irrelevant to the parser)
        1,  # e_version
        0,  # e_entry
        e_phoff,  # e_phoff
        0,  # e_shoff
        0,  # e_flags
        _EHSIZE,  # e_ehsize
        e_phentsize,  # e_phentsize
        e_phnum,  # e_phnum
        0,  # e_shentsize
        0,  # e_shnum
        0,  # e_shstrndx
    )
    header = ident + rest
    assert len(header) == _EHSIZE
    return header


def _program_header(p_type: int) -> bytes:
    """One real little-endian ``Elf64_Phdr`` of the given ``p_type``."""
    entry = struct.pack("<II", p_type, 0) + struct.pack(
        "<QQQQQQ", 0, 0, 0, 0, 0, 0x1000
    )
    assert len(entry) == _PHENTSIZE
    return entry


def _static_elf(*, segments: list[int] | None = None) -> bytes:
    """A complete, well-formed static ELF64: the one baseline every tamper edits."""
    types = segments if segments is not None else [_PT_LOAD]
    return _elf64_header(e_phnum=len(types)) + b"".join(
        _program_header(kind) for kind in types
    )


def _open(path: Path, data: bytes) -> int:
    path.write_bytes(data)
    return os.open(path, os.O_RDWR)


def test_a_well_formed_static_elf_is_accepted(tmp_path: Path) -> None:
    """The baseline fixture itself must pass before any tamper of it proves anything."""
    fd = _open(tmp_path / "helper", _static_elf())
    try:
        require_unprivileged_static_helper(fd)
    finally:
        os.close(fd)


def test_a_plain_text_file_is_refused(tmp_path: Path) -> None:
    fd = _open(tmp_path / "helper", b"#!/bin/sh\necho not an elf\n")
    try:
        with pytest.raises(ValueError, match="must be a static ELF executable"):
            require_unprivileged_static_helper(fd)
    finally:
        os.close(fd)


def test_a_header_truncated_before_its_own_declared_size_is_refused(
    tmp_path: Path,
) -> None:
    """Cut mid-header: the magic and class parse, but the ``Ehdr`` itself is short."""
    truncated = _static_elf()[:60]
    assert 52 <= len(truncated) < _EHSIZE
    fd = _open(tmp_path / "helper", truncated)
    try:
        with pytest.raises(ValueError, match="ELF header is truncated"):
            require_unprivileged_static_helper(fd)
    finally:
        os.close(fd)


def test_a_zero_program_header_count_is_refused(tmp_path: Path) -> None:
    fd = _open(tmp_path / "helper", _elf64_header(e_phnum=0))
    try:
        with pytest.raises(ValueError, match="ELF program headers are invalid"):
            require_unprivileged_static_helper(fd)
    finally:
        os.close(fd)


def test_a_dynamic_or_interpreter_segment_is_refused(tmp_path: Path) -> None:
    """PT_DYNAMIC (2) and PT_INTERP (3) are what the launcher calls "dynamic"."""
    for kind in (2, 3):
        fd = _open(tmp_path / f"helper-{kind}", _static_elf(segments=[_PT_LOAD, kind]))
        try:
            with pytest.raises(
                ValueError, match="must not use host dynamic dependencies"
            ):
                require_unprivileged_static_helper(fd)
        finally:
            os.close(fd)


@pytest.mark.skipif(os.name == "nt", reason="setuid/setgid bits are POSIX-only")
def test_a_setuid_or_setgid_helper_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "helper"
    path.write_bytes(_static_elf())
    for bits in (0o4755, 0o2755):
        path.chmod(bits)
        fd = os.open(path, os.O_RDWR)
        try:
            with pytest.raises(ValueError, match="cannot have privileged mode bits"):
                require_unprivileged_static_helper(fd)
        finally:
            os.close(fd)
