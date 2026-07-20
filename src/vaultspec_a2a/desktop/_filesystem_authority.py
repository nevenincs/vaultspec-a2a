"""Private native filesystem authority for capsule publication."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Iterator


_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_TRAVERSE = 0x00000020
_FILE_GENERIC_READ = 0x80000000
_FILE_GENERIC_WRITE = 0x40000000
_DELETE = 0x00010000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_CREATE_NEW = 1
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_RENAME_INFORMATION_CLASS = 10
_AT_FDCWD = -100
_AT_EMPTY_PATH = 0x1000
_AT_SYMLINK_FOLLOW = 0x400


class _NativeFunction(Protocol):
    argtypes: tuple[object, ...]
    restype: object

    def __call__(self, *args: object) -> object: ...


class _WindowsLibrary(Protocol):
    CreateFileW: _NativeFunction
    CloseHandle: _NativeFunction
    GetFileInformationByHandle: _NativeFunction


class _WindowsNativeLibrary(Protocol):
    NtSetInformationFile: _NativeFunction
    RtlNtStatusToDosError: _NativeFunction


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", ctypes.c_uint32),
        ("creation_time", ctypes.c_uint32 * 2),
        ("access_time", ctypes.c_uint32 * 2),
        ("write_time", ctypes.c_uint32 * 2),
        ("volume_serial", ctypes.c_uint32),
        ("size_high", ctypes.c_uint32),
        ("size_low", ctypes.c_uint32),
        ("link_count", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    ]


class _FileRenameInformation(ctypes.Structure):
    _fields_ = [
        ("replace_if_exists", ctypes.c_ubyte),
        ("root_directory", ctypes.c_void_p),
        ("file_name_length", ctypes.c_uint32),
        ("file_name", ctypes.c_wchar * 1),
    ]


class _IoStatusBlock(ctypes.Structure):
    _fields_ = [
        ("status_or_pointer", ctypes.c_void_p),
        ("information", ctypes.c_size_t),
    ]


@dataclass(frozen=True, slots=True)
class DirectoryAuthority:
    """Canonical directory identity plus one live native lease."""

    path: Path
    identity: tuple[int, int]
    dir_fd: int | None = None
    native_handle: int | None = None


def path_is_link_like(path: Path) -> bool:
    """Return whether *path* is a symlink or Windows junction."""
    return path.is_symlink() or path.is_junction()


def _directory_identity(path: Path) -> tuple[int, int]:
    metadata = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(metadata.st_mode):
        raise NotADirectoryError(errno.ENOTDIR, "authority is not a directory", path)
    return metadata.st_dev, metadata.st_ino


def resolve_directory_authority(path: Path) -> DirectoryAuthority:
    """Resolve one real, non-link-like directory before leasing it."""
    if not isinstance(path, Path):
        raise TypeError("directory authority path must be a Path")
    if path_is_link_like(path):
        raise OSError(errno.ELOOP, "directory authority is link-like", path)
    before = _directory_identity(path)
    canonical = path.resolve(strict=True)
    after = _directory_identity(path)
    canonical_identity = _directory_identity(canonical)
    if before != after or after != canonical_identity:
        raise OSError(errno.ESTALE, "directory authority changed while resolving", path)
    return DirectoryAuthority(path=canonical, identity=canonical_identity)


def _windows_library() -> _WindowsLibrary:
    return cast(
        "_WindowsLibrary",
        ctypes.WinDLL("kernel32", use_last_error=True),
    )


def _windows_native_library() -> _WindowsNativeLibrary:
    return cast(
        "_WindowsNativeLibrary",
        ctypes.WinDLL("ntdll"),
    )


def _last_windows_error(path: Path) -> OSError:
    error = int(ctypes.get_last_error())
    return OSError(error, ctypes.FormatError(error), path)


def _windows_handle_identity(
    library: _WindowsLibrary, handle: int, path: Path
) -> tuple[int, int]:
    get_information = library.GetFileInformationByHandle
    get_information.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    get_information.restype = ctypes.c_int
    information = _ByHandleFileInformation()
    if not get_information(handle, ctypes.byref(information)):
        raise _last_windows_error(path)
    if not information.attributes & _FILE_ATTRIBUTE_DIRECTORY:
        raise NotADirectoryError(
            errno.ENOTDIR, "leased authority is not a directory", path
        )
    file_index = (information.file_index_high << 32) | information.file_index_low
    return information.volume_serial, file_index


def _assert_windows_authority(authority: DirectoryAuthority) -> None:
    if authority.native_handle is None:
        raise OSError(errno.EBADF, "Windows directory authority is not leased")
    named = _directory_identity(authority.path)
    if named != authority.identity or path_is_link_like(authority.path):
        raise OSError(
            errno.ESTALE, "Windows directory authority changed", authority.path
        )
    _, file_index = _windows_handle_identity(
        _windows_library(), authority.native_handle, authority.path
    )
    if file_index != authority.identity[1]:
        raise OSError(
            errno.ESTALE,
            "Windows directory lease changed identity",
            authority.path,
        )


def assert_directory_authority(authority: DirectoryAuthority) -> None:
    """Validate the named directory and any live native lease."""
    if authority.native_handle is not None:
        _assert_windows_authority(authority)
        return
    named = _directory_identity(authority.path)
    if named != authority.identity or path_is_link_like(authority.path):
        raise OSError(errno.ESTALE, "directory authority changed", authority.path)
    if authority.dir_fd is not None:
        opened = os.fstat(authority.dir_fd)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (
                opened.st_dev,
                opened.st_ino,
            )
            != authority.identity
        ):
            raise OSError(
                errno.ESTALE, "directory lease changed identity", authority.path
            )


@contextmanager
def _windows_directory_lease(
    authority: DirectoryAuthority,
    *,
    publication: bool,
) -> Iterator[DirectoryAuthority]:
    library = _windows_library()
    create_file = library.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p
    handle_value = create_file(
        str(authority.path),
        _FILE_READ_ATTRIBUTES | _FILE_TRAVERSE | (_DELETE if publication else 0),
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle_value in {None, invalid_handle}:
        raise _last_windows_error(authority.path)
    handle = cast("int", handle_value)
    leased = replace(authority, native_handle=handle)
    close_handle = library.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int
    try:
        assert_directory_authority(leased)
        yield leased
        _, file_index = _windows_handle_identity(library, handle, authority.path)
        if file_index != authority.identity[1]:
            raise OSError(errno.ESTALE, "Windows directory lease changed identity")
    finally:
        if not close_handle(handle):
            raise _last_windows_error(authority.path)


@contextmanager
def directory_lease(
    authority: DirectoryAuthority,
    *,
    publication: bool = False,
) -> Iterator[DirectoryAuthority]:
    """Hold a live native lease for one directory identity."""
    assert_directory_authority(authority)
    if os.name == "nt":
        with _windows_directory_lease(authority, publication=publication) as leased:
            yield leased
        return
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise OSError(
            errno.ENOSYS,
            "POSIX directory leases require O_DIRECTORY and O_NOFOLLOW",
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(authority.path, flags)
    leased = replace(authority, dir_fd=descriptor)
    try:
        assert_directory_authority(leased)
        yield leased
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != authority.identity:
            raise OSError(errno.ESTALE, "directory lease changed identity")
    finally:
        os.close(descriptor)


def _validate_relative_name(value: str) -> bytes:
    if (
        not isinstance(value, str)
        or value in {"", ".", ".."}
        or "/" in value
        or "\\" in value
        or Path(value).name != value
    ):
        raise ValueError("publication names must be single relative components")
    return os.fsencode(value)


@contextmanager
def claim_new_directory(
    authority: DirectoryAuthority,
    name: str,
) -> Iterator[DirectoryAuthority]:
    """Require an absent child name, then lease its current empty directory.

    Creation is atomic and refuses replacement, but portable POSIX ``mkdir`` does
    not return a descriptor. A same-user actor can therefore substitute another
    child before the no-follow lease is acquired. This function intentionally
    claims only that the leased authority is the current child, not that its inode
    is necessarily the inode created by ``mkdir``. It verifies that current child
    is empty before yielding and continuously holds its exact authority afterward.

    The caller retains exclusive mutation authority over the leased parent. A
    pre-lease substitution poisons only the caller-owned unpublished generation;
    failure never cleans or publishes any name, and the enclosing transaction must
    discard the whole unreceipted generation.
    """
    _validate_relative_name(name)
    assert_directory_authority(authority)
    child_path = authority.path / name

    if os.name == "nt":
        if authority.native_handle is None or authority.dir_fd is not None:
            raise OSError(errno.EBADF, "Windows parent authority is not leased")
        child_path.mkdir(mode=0o700)
        child_authority = resolve_directory_authority(child_path)
        with _windows_directory_lease(
            child_authority,
            publication=False,
        ) as child_lease:
            assert_directory_authority(authority)
            assert_empty_directory_authority(child_lease)
            yield child_lease
            assert_directory_authority(authority)
        return

    if authority.dir_fd is None or authority.native_handle is not None:
        raise OSError(errno.EBADF, "POSIX parent authority is not leased")
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise OSError(
            errno.ENOSYS,
            "POSIX directory claims require O_DIRECTORY and O_NOFOLLOW",
        )

    os.mkdir(name, mode=0o700, dir_fd=authority.dir_fd)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(name, flags, dir_fd=authority.dir_fd)
    try:
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=authority.dir_fd, follow_symlinks=False)
        identity = (opened.st_dev, opened.st_ino)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or identity != (named.st_dev, named.st_ino)
        ):
            raise OSError(
                errno.ESTALE,
                "current POSIX child changed while acquiring its lease",
                child_path,
            )
        child_lease = DirectoryAuthority(
            path=child_path,
            identity=identity,
            dir_fd=descriptor,
        )
        assert_directory_authority(authority)
        assert_empty_directory_authority(child_lease)
        yield child_lease
        assert_directory_authority(child_lease)
        assert_directory_authority(authority)
    finally:
        os.close(descriptor)


def assert_empty_directory_authority(authority: DirectoryAuthority) -> None:
    """Require one leased directory authority to be empty without mutation.

    POSIX enumerates the exact held directory descriptor. Windows revalidates
    the held non-delete-shared identity and its path immediately around pathname
    enumeration. The caller's exclusive-mutation precondition remains in force.
    """
    assert_directory_authority(authority)
    if authority.dir_fd is not None:
        with os.scandir(authority.dir_fd) as entries:
            occupied = next(entries, None) is not None
        assert_directory_authority(authority)
    elif os.name == "nt" and authority.native_handle is not None:
        with os.scandir(authority.path) as entries:
            occupied = next(entries, None) is not None
        assert_directory_authority(authority)
    else:
        raise OSError(errno.EBADF, "directory authority is not leased")
    if occupied:
        raise OSError(
            errno.ENOTEMPTY,
            "unpublished generation directory is not empty",
            authority.path,
        )


def create_private_file(authority: DirectoryAuthority, name: str) -> BinaryIO:
    """Atomically claim one private regular-file slot beneath *authority*.

    The Windows handle is created with delete authority so the exact live file
    object can later be renamed without reopening its pathname.
    """
    _validate_relative_name(name)
    assert_directory_authority(authority)
    if os.name == "nt":
        import msvcrt

        if authority.native_handle is None or authority.dir_fd is not None:
            raise OSError(errno.EBADF, "Windows file authority is not leased")
        library = _windows_library()
        create_file = library.CreateFileW
        create_file.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        )
        create_file.restype = ctypes.c_void_p
        handle_value = create_file(
            str(authority.path / name),
            _FILE_GENERIC_READ | _FILE_GENERIC_WRITE | _DELETE,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _CREATE_NEW,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle_value in {None, invalid_handle}:
            error = int(ctypes.get_last_error())
            if error in {80, 183}:
                raise FileExistsError(errno.EEXIST, "private file slot exists", name)
            raise _last_windows_error(authority.path / name)
        handle = cast("int", handle_value)
        try:
            descriptor = msvcrt.open_osfhandle(
                handle,
                os.O_RDWR | getattr(os, "O_BINARY", 0),
            )
        except BaseException:
            close_handle = library.CloseHandle
            close_handle.argtypes = (ctypes.c_void_p,)
            close_handle.restype = ctypes.c_int
            close_handle(handle)
            raise
        try:
            return os.fdopen(descriptor, "w+b", buffering=0, closefd=True)
        except BaseException:
            os.close(descriptor)
            raise
    if authority.dir_fd is None or authority.native_handle is not None:
        raise OSError(errno.EBADF, "POSIX file authority is not leased")
    if not hasattr(os, "O_NOFOLLOW"):
        raise OSError(errno.ENOSYS, "POSIX private files require O_NOFOLLOW")
    descriptor = os.open(
        name,
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | os.O_NOFOLLOW,
        0o600,
        dir_fd=authority.dir_fd,
    )
    try:
        return os.fdopen(descriptor, "w+b", buffering=0, closefd=True)
    except BaseException:
        os.close(descriptor)
        raise


def create_anonymous_file(authority: DirectoryAuthority) -> BinaryIO:
    """Create a Linux anonymous regular file beneath the leased authority."""
    assert_directory_authority(authority)
    if (
        os.name == "nt"
        or not sys.platform.startswith("linux")
        or authority.dir_fd is None
        or not hasattr(os, "O_TMPFILE")
    ):
        raise OSError(errno.ENOSYS, "anonymous descriptor staging is unsupported")
    descriptor = os.open(
        ".",
        os.O_RDWR | os.O_TMPFILE | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=authority.dir_fd,
    )
    try:
        return os.fdopen(descriptor, "w+b", buffering=0, closefd=True)
    except BaseException:
        os.close(descriptor)
        raise


def _posix_function(name: str) -> _NativeFunction:
    library = ctypes.CDLL(None, use_errno=True)
    function = getattr(library, name, None)
    if function is None:
        raise OSError(errno.ENOSYS, f"native {name} is unavailable")
    return cast("_NativeFunction", function)


def _windows_publish_handle(
    authority: DirectoryAuthority,
    source_handle: int,
    destination_name: str,
) -> None:
    if authority.native_handle is None:
        raise OSError(errno.EBADF, "Windows publication authority is not leased")
    encoded_name = destination_name.encode("utf-16-le")
    name_offset = _FileRenameInformation.file_name.offset
    buffer = ctypes.create_string_buffer(
        ctypes.sizeof(_FileRenameInformation) + len(encoded_name)
    )
    information = _FileRenameInformation.from_buffer(buffer)
    information.replace_if_exists = 0
    information.root_directory = authority.native_handle
    information.file_name_length = len(encoded_name)
    ctypes.memmove(
        ctypes.addressof(buffer) + name_offset,
        encoded_name,
        len(encoded_name),
    )
    library = _windows_native_library()
    set_information = library.NtSetInformationFile
    set_information.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
    )
    set_information.restype = ctypes.c_long
    io_status = _IoStatusBlock()
    status = cast(
        "int",
        set_information(
            source_handle,
            ctypes.byref(io_status),
            buffer,
            len(buffer),
            _FILE_RENAME_INFORMATION_CLASS,
        ),
    )
    if status >= 0:
        return
    status_to_error = library.RtlNtStatusToDosError
    status_to_error.argtypes = (ctypes.c_long,)
    status_to_error.restype = ctypes.c_ulong
    error = cast("int", status_to_error(status))
    if error in {80, 183}:
        raise FileExistsError(
            errno.EEXIST,
            "publication destination exists",
            authority.path / destination_name,
        )
    raise OSError(
        error,
        ctypes.FormatError(error),
        authority.path / destination_name,
    )


def _posix_link_fd_no_replace(
    authority: DirectoryAuthority,
    source_fd: int,
    destination_bytes: bytes,
) -> None:
    if not sys.platform.startswith("linux") or authority.dir_fd is None:
        raise OSError(errno.ENOSYS, "descriptor-bound file publication unsupported")
    link = _posix_function("linkat")
    link.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    )
    link.restype = ctypes.c_int
    if link(source_fd, b"", authority.dir_fd, destination_bytes, _AT_EMPTY_PATH) == 0:
        return
    empty_path_error = ctypes.get_errno()
    proc_source = os.fsencode(f"/proc/self/fd/{source_fd}")
    if (
        link(
            _AT_FDCWD,
            proc_source,
            authority.dir_fd,
            destination_bytes,
            _AT_SYMLINK_FOLLOW,
        )
        == 0
    ):
        return
    error = ctypes.get_errno()
    if error == 0:
        error = empty_path_error
    raise OSError(
        error, os.strerror(error), authority.path / os.fsdecode(destination_bytes)
    )


def publish_no_replace(
    authority: DirectoryAuthority,
    source_name: str,
    destination_name: str,
    *,
    source_fd: int | None = None,
    source_authority: DirectoryAuthority | None = None,
) -> None:
    """Publish a held source without replacing an existing destination.

    Windows renames the exact held handle. Linux can link an anonymous file by
    its exact descriptor. Named POSIX sources and POSIX directories fail closed
    because native rename APIs would re-resolve the source name after authority
    validation and could therefore publish a swapped object.
    """
    source_bytes = _validate_relative_name(source_name)
    destination_bytes = _validate_relative_name(destination_name)
    if source_bytes == destination_bytes:
        raise ValueError("publication source and destination must differ")
    if (source_fd is None) == (source_authority is None):
        raise ValueError("publication requires exactly one live source authority")
    assert_directory_authority(authority)
    if os.name == "nt":
        if authority.native_handle is None or authority.dir_fd is not None:
            raise OSError(errno.EBADF, "Windows publication authority is not leased")
        if source_fd is not None:
            import msvcrt

            opened = os.fstat(source_fd)
            if not stat.S_ISREG(opened.st_mode):
                raise OSError(errno.EINVAL, "file publication source is not regular")
            source_handle = msvcrt.get_osfhandle(source_fd)
        else:
            assert source_authority is not None
            assert_directory_authority(source_authority)
            if source_authority.native_handle is None:
                raise OSError(errno.EBADF, "Windows source authority is not leased")
            source_handle = source_authority.native_handle
        _windows_publish_handle(authority, source_handle, destination_name)
        return
    if authority.dir_fd is None or authority.native_handle is not None:
        raise OSError(errno.EBADF, "POSIX publication authority is not leased")
    if source_fd is not None:
        opened = os.fstat(source_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(errno.EINVAL, "file publication source is not regular")
        if opened.st_nlink == 0:
            _posix_link_fd_no_replace(authority, source_fd, destination_bytes)
            return
        raise OSError(
            errno.ENOSYS,
            "named POSIX file publication is not identity-bound",
        )
    assert source_authority is not None
    assert_directory_authority(source_authority)
    if source_authority.dir_fd is None or source_authority.native_handle is not None:
        raise OSError(errno.EBADF, "POSIX source authority is not leased")
    opened = os.fstat(source_authority.dir_fd)
    if not stat.S_ISDIR(opened.st_mode):
        raise OSError(errno.EINVAL, "directory publication source is not a directory")
    raise OSError(
        errno.ENOSYS,
        "POSIX directory publication is not identity-bound",
    )
