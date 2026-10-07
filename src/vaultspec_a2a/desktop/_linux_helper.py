"""Self-contained ELF validation and sealed helper arguments."""

from __future__ import annotations

import ctypes
import os
import stat
import struct

__all__ = [
    "PRIVILEGED_MODE_BITS",
    "anonymous_arguments",
    "anonymous_data",
    "require_unprivileged_static_helper",
]

PRIVILEGED_MODE_BITS = stat.S_ISUID | stat.S_ISGID


def require_unprivileged_static_helper(descriptor: int) -> None:
    """Reject a privileged or dynamically linked helper before executing it."""
    _require_static_elf(descriptor)
    if os.fstat(descriptor).st_mode & PRIVILEGED_MODE_BITS:
        raise ValueError("native helper cannot have privileged mode bits")


def _require_static_elf(descriptor: int) -> None:
    """Reject interpreter/dynamic dependencies before executing a helper input."""
    os.lseek(descriptor, 0, os.SEEK_SET)
    header = os.read(descriptor, 64)
    if (
        len(header) < 52
        or header[:4] != b"\x7fELF"
        or header[4] not in {1, 2}
        or header[5] not in {1, 2}
    ):
        raise ValueError("native helper must be a static ELF executable")
    endian = "<" if header[5] == 1 else ">"
    if struct.unpack_from(endian + "H", header, 16)[0] != 2:
        raise ValueError("native helper must be a static ELF executable")
    if header[4] == 2:
        if len(header) < 64:
            raise ValueError("native helper ELF header is truncated")
        offset = struct.unpack_from(endian + "Q", header, 32)[0]
        entry_size, count = struct.unpack_from(endian + "HH", header, 54)
        minimum, header_size = 56, 64
    else:
        offset = struct.unpack_from(endian + "I", header, 28)[0]
        entry_size, count = struct.unpack_from(endian + "HH", header, 42)
        minimum, header_size = 32, 52
    length = entry_size * count
    if (
        not 1 <= count <= 1024
        or not minimum <= entry_size <= 128
        or offset < header_size
        or offset + length > os.fstat(descriptor).st_size
    ):
        raise ValueError("native helper ELF program headers are invalid")
    os.lseek(descriptor, offset, os.SEEK_SET)
    table = os.read(descriptor, length)
    if len(table) != length or any(
        struct.unpack_from(endian + "I", table, index * entry_size)[0] in {2, 3}
        for index in range(count)
    ):
        raise ValueError("native helper must not use host dynamic dependencies")
    os.lseek(descriptor, 0, os.SEEK_SET)


def anonymous_arguments(arguments: list[str]) -> int:
    """Return a sealed memfd; bubblewrap consumes and closes it before target exec."""
    return anonymous_data(b"\0".join(arg.encode("utf-8") for arg in arguments) + b"\0")


def anonymous_data(data: bytes) -> int:
    """Return immutable anonymous bytes without granting their host source."""
    native_libc = ctypes.CDLL(None, use_errno=True)
    create_memfd = native_libc.memfd_create
    create_memfd.argtypes = [ctypes.c_char_p, ctypes.c_uint]
    create_memfd.restype = ctypes.c_int
    # Linux UAPI MFD_CLOEXEC | MFD_ALLOW_SEALING. Some locked standalone CPython
    # builds omit os.memfd_create and the equivalent fcntl constants.
    descriptor = create_memfd(b"native-isolation-data", 0x0001 | 0x0002)
    if descriptor < 0:
        raise OSError(ctypes.get_errno(), "native argument memfd creation failed")
    try:
        with os.fdopen(os.dup(descriptor), "wb") as stream:
            stream.write(data)
        os.lseek(descriptor, 0, os.SEEK_SET)
        seal_memfd = native_libc.fcntl
        seal_memfd.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        seal_memfd.restype = ctypes.c_int
        # Linux UAPI F_ADD_SEALS; SEAL_SEAL | SHRINK | GROW | WRITE.
        if seal_memfd(descriptor, 1033, 0x000F) < 0:
            raise OSError(ctypes.get_errno(), "native argument memfd sealing failed")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise
