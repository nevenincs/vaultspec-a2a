"""Private native filesystem authority for capsule publication."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
import time
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
#: Windows ``ERROR_SHARING_VIOLATION``. Raised when another process holds the
#: target without sharing the access being requested - transient by nature here,
#: because the other holder is a peer mid-lease, or a scanner sampling a file
#: this process created microseconds ago, rather than a permanent owner.
_ERROR_SHARING_VIOLATION = 32
#: How long the two publication paths - the directory lease and the rename that
#: publishes a held handle - ride out a sharing violation before giving up.
#: Long enough to outlast a peer's lease or a scanner's sample, short enough that
#: a genuinely wedged holder still surfaces as an error rather than a stall.
#:
#: Sized at ten seconds because two was measured too short. The credential is
#: created, written, fsynced and re-ACLed within microseconds, and re-ACLing goes
#: through `SetNamedSecurityInfoW`, which opens the file BY NAME - so a real-time
#: scanner is invited to sample a brand-new secret at exactly the moment the
#: rename needs delete-class access to it. On a loaded CI runner that sample
#: outlived a two-second budget on every Windows release attempt. Nothing here
#: masks a wedged holder: one holds indefinitely and still fails loudly.
_SHARING_RETRY_SECONDS = 10.0
_SHARING_RETRY_INTERVAL_SECONDS = 0.02

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
    if sys.platform != "win32":
        raise OSError(errno.ENOSYS, "kernel32 is available only on Windows")
    return cast(
        "_WindowsLibrary",
        ctypes.WinDLL("kernel32", use_last_error=True),
    )


def _windows_native_library() -> _WindowsNativeLibrary:
    if sys.platform != "win32":
        raise OSError(errno.ENOSYS, "ntdll is available only on Windows")
    return cast(
        "_WindowsNativeLibrary",
        ctypes.WinDLL("ntdll"),
    )


def _create_file_w(library: _WindowsLibrary) -> _NativeFunction:
    """Return ``CreateFileW`` with its one canonical prototype declared.

    Every native call site in this module - the directory lease and the private
    file claim - reaches kernel32 through here. Two independently maintained
    ``argtypes`` tuples for one native function is not a style concern: a tuple
    that drifts from its call site corrupts argument marshalling in a call that
    creates and deletes files under this module's security authority, and it does
    so silently, with no exception to observe and nothing for a test to catch.
    Declared once, the call sites differ only where they genuinely differ - the
    path, access mask, share mode, disposition and flags that distinguish leasing
    a directory from claiming a file.
    """
    create_file = library.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,  # lpFileName
        ctypes.c_uint32,  # dwDesiredAccess
        ctypes.c_uint32,  # dwShareMode
        ctypes.c_void_p,  # lpSecurityAttributes
        ctypes.c_uint32,  # dwCreationDisposition
        ctypes.c_uint32,  # dwFlagsAndAttributes
        ctypes.c_void_p,  # hTemplateFile
    )
    create_file.restype = ctypes.c_void_p
    return create_file


def _close_handle(library: _WindowsLibrary) -> _NativeFunction:
    """Return ``CloseHandle`` with its one canonical prototype declared.

    Same reasoning as :func:`_create_file_w`: this is the release half of the
    handle contract, and a drifting prototype here would mis-marshal the handle
    being closed rather than fail loudly.
    """
    close_handle = library.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)  # hObject
    close_handle.restype = ctypes.c_int
    return close_handle


def _windows_error(error: int, path: Path) -> OSError:
    """Build an :class:`OSError` that carries *error* as a WINDOWS error code.

    The three-argument form puts its first argument in ``errno``, so a Windows
    code lands in the POSIX slot and Python picks the exception class from it.
    ``ERROR_SHARING_VIOLATION`` (32) then arrives as ``BrokenPipeError``, because
    32 is ``EPIPE`` - carrying the correct Windows message, the wrong class, and
    no ``winerror`` at all. A caller cannot classify that, and a diagnosis reading
    "broken pipe" for a file another process is holding sends the next reader the
    wrong way entirely.

    The four-argument form is the one that means "this is a Windows code": it
    selects the class from the winerror and fills ``errno`` from the platform's
    own mapping, so both ``isinstance`` and ``exc.winerror`` answer truthfully.
    """
    return OSError(0, ctypes.FormatError(error), str(path), error)


def _last_windows_error(path: Path) -> OSError:
    if sys.platform != "win32":
        raise OSError(errno.ENOSYS, "Windows error codes are unavailable", path)
    return _windows_error(int(ctypes.get_last_error()), path)


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
    create_file = _create_file_w(library)
    invalid_handle = ctypes.c_void_p(-1).value
    # A publication lease additionally asks for DELETE, which a concurrent holder
    # of this directory need not be sharing. That collision is TRANSIENT - the
    # other holder is itself mid-lease and about to release - so it is ridden out
    # rather than raised, the same treatment the atomic writer already gives the
    # identical Windows sharing violation on its rename.
    #
    # Raising immediately here is not a smaller failure than a hang: this lease
    # guards the discovery heartbeat, so a single lost race stops a live service
    # publishing where it can be found, permanently and silently, on any machine
    # where a second process touches the directory. That is precisely the
    # multi-session case this project runs in.
    deadline = time.monotonic() + _SHARING_RETRY_SECONDS
    while True:
        handle_value = create_file(
            str(authority.path),
            _FILE_READ_ATTRIBUTES | _FILE_TRAVERSE | (_DELETE if publication else 0),
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if handle_value not in {None, invalid_handle}:
            break
        error = _last_windows_error(authority.path)
        # Keyed on winerror, never errno: these are Windows codes, and the two
        # numbering spaces collide silently - 32 is ERROR_SHARING_VIOLATION here
        # and EPIPE there, so an errno comparison would match the right failure
        # for the wrong reason and stop matching the moment the error is
        # constructed correctly.
        if error.winerror != _ERROR_SHARING_VIOLATION or time.monotonic() >= deadline:
            raise error
        time.sleep(_SHARING_RETRY_INTERVAL_SECONDS)
    handle = cast("int", handle_value)
    leased = replace(authority, native_handle=handle)
    close_handle = _close_handle(library)
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
        create_file = _create_file_w(library)
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
            _close_handle(library)(handle)
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
    if sys.platform != "win32":
        raise OSError(errno.ENOSYS, "Windows publication requires Windows")
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
    status_to_error = library.RtlNtStatusToDosError
    status_to_error.argtypes = (ctypes.c_long,)
    status_to_error.restype = ctypes.c_ulong
    # A rename is a delete-class operation on the source, so ANY peer holding
    # that file without sharing DELETE denies it - and the peer need not be
    # another instance of this program. A real-time scanner sampling a file this
    # process created, wrote and re-ACLed microseconds earlier is the ordinary
    # case, and it lets go on its own.
    #
    # This is the last rename in the package that failed a live publication on
    # someone else's momentary handle: the atomic writer already rides the
    # identical violation out on its replace, and the directory lease above does
    # the same on its open. Riding it out here costs a bounded wait and gives up
    # loudly at the deadline, so a genuinely wedged holder still surfaces rather
    # than stalling a gateway that cannot publish where it can be found.
    deadline = time.monotonic() + _SHARING_RETRY_SECONDS
    while True:
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
        error = cast("int", status_to_error(status))
        if error != _ERROR_SHARING_VIOLATION or time.monotonic() >= deadline:
            break
        time.sleep(_SHARING_RETRY_INTERVAL_SECONDS)
    if error in {80, 183}:
        raise FileExistsError(
            errno.EEXIST,
            "publication destination exists",
            str(authority.path / destination_name),
        )
    raise _windows_error(error, authority.path / destination_name)


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
