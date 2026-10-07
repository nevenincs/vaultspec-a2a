"""Cross-platform owner-restriction primitives for local credential files.

Single authority for the questions asked of every local secret file this product
writes or reads: "make this file reachable only by its owner" and "is this file
owner-restricted?". The answer spans POSIX permission bits and Windows
discretionary access-control lists (DACLs). The gateway discovery credential and
the desktop attach, ownership, and worker-interprocess-communication (IPC)
credentials all protect a local secret with the same guarantee, so the native
Windows ACL machinery lives here once rather than being restated in each consumer.

The Windows helpers stay read-only where they inspect and use only native ACL APIs
where they mutate; no third-party dependency is required. On POSIX the guarantee is
ownership by the current effective user with no group or other access; the state
and credential predicates differ, on purpose, in how exact the mode must be.
"""

from __future__ import annotations

import ctypes
import os
import stat
import subprocess
from csv import reader as csv_reader
from enum import Enum, auto
from functools import cache
from pathlib import Path

from ..utils import path_is_link_like

__all__ = [
    "confirm_opened_secret",
    "credential_file_is_owner_restricted",
    "harden_credential_path",
    "owner_only_mode",
    "path_is_owner_restricted",
    "restrict_windows_file",
    "unfollowed_read_flags",
    "windows_file_is_restricted",
]


class _OwnerRule(Enum):
    """The two owner-only rules, applied by the predicate named for each."""

    STATE = auto()
    CREDENTIAL = auto()


class _AclSizeInformation(ctypes.Structure):
    _fields_ = (
        ("ace_count", ctypes.c_uint32),
        ("acl_bytes_in_use", ctypes.c_uint32),
        ("acl_bytes_free", ctypes.c_uint32),
    )


class _AceHeader(ctypes.Structure):
    _fields_ = (
        ("ace_type", ctypes.c_ubyte),
        ("ace_flags", ctypes.c_ubyte),
        ("ace_size", ctypes.c_ushort),
    )


@cache
def _windows_system_executable(name: str) -> str:
    """Resolve a trusted executable directly from the native system directory."""
    if os.name != "nt" or Path(name).name != name:
        raise OSError("trusted Windows executable resolution is unavailable")
    buffer = ctypes.create_unicode_buffer(32_768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if length <= 0 or length >= len(buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    executable = Path(buffer.value) / name
    if not executable.is_file():
        raise FileNotFoundError(executable)
    return str(executable)


@cache
def windows_current_user_sid() -> str:
    """Resolve the current Windows account SID without localized name parsing."""
    # Only the SID column is read, and a SID is ASCII by construction - but the
    # account name sharing the row is not, and a strict locale decode of a
    # non-ASCII account name fails inside subprocess's reader thread, leaving
    # ``stdout`` as None and this function raising AttributeError instead of
    # resolving a SID that was perfectly readable. Degrading the name keeps the
    # SID intact.
    #
    # The decode is deliberately left to the locale here, and that is safe for a
    # structural reason rather than an incidental one: nothing localized is ever
    # compared. ``/fo csv /nh`` is a machine format, so no header or display
    # label is emitted at all, and the SID is identified by its ``S-1-`` prefix -
    # a token no UI language rewrites - with the row arity and that prefix both
    # asserted below. A mangled account name therefore cannot produce a wrong
    # SID; it can only fail the check, which raises rather than returning a
    # plausible-looking wrong principal to a DACL.
    completed = subprocess.run(
        [_windows_system_executable("whoami.exe"), "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    row = next(csv_reader([completed.stdout.strip()]))
    if len(row) != 2 or not row[1].startswith("S-1-"):
        msg = "unable to resolve current Windows account SID"
        raise OSError(msg)
    return row[1]


def restrict_windows_file(path: Path) -> None:
    """Replace the DACL with user, SYSTEM, and administrators full access."""
    if os.name != "nt":
        return
    current_sid = windows_current_user_sid()
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor = ctypes.c_void_p()
    inheritance = "OICI" if path.is_dir() else ""
    sddl = (
        f"D:P(A;{inheritance};FA;;;{current_sid})"
        f"(A;{inheritance};FA;;;SY)(A;{inheritance};FA;;;BA)"
    )
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl,
        1,  # SDDL_REVISION_1
        ctypes.byref(descriptor),
        None,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        dacl = ctypes.c_void_p()
        present = ctypes.c_int()
        defaulted = ctypes.c_int()
        if not advapi32.GetSecurityDescriptorDacl(
            descriptor,
            ctypes.byref(present),
            ctypes.byref(dacl),
            ctypes.byref(defaulted),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not present.value or not dacl.value:
            raise OSError("private Windows DACL is absent")
        result = advapi32.SetNamedSecurityInfoW(
            str(path),
            1,  # SE_FILE_OBJECT
            0x00000004 | 0x80000000,  # DACL + PROTECTED_DACL
            None,
            None,
            dacl,
            None,
        )
        if result:
            raise OSError(result, ctypes.FormatError(result), path)
    finally:
        kernel32.LocalFree(descriptor)


def _restricted_dacl_principals(
    dacl: ctypes.c_void_p, *, allow_inherited: bool = False
) -> set[str] | None:
    """Read allowed principals, rejecting inherited or non-allow ACEs."""
    if os.name != "nt":
        return None
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    information = _AclSizeInformation()
    if not advapi32.GetAclInformation(
        dacl,
        ctypes.byref(information),
        ctypes.sizeof(information),
        2,  # AclSizeInformation
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    principals: set[str] = set()
    for index in range(information.ace_count):
        ace = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, index, ctypes.byref(ace)):
            raise ctypes.WinError(ctypes.get_last_error())
        header = ctypes.cast(ace, ctypes.POINTER(_AceHeader)).contents
        if header.ace_type != 0 or (header.ace_flags & 0x10 and not allow_inherited):
            return None
        ace_address = ace.value
        if ace_address is None:
            return None
        sid = ctypes.c_void_p(ace_address + ctypes.sizeof(_AceHeader) + 4)
        rendered = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(rendered)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if rendered.value is None:
                return None
            principals.add(rendered.value)
        finally:
            kernel32.LocalFree(rendered)
    return principals


def windows_file_is_restricted(path: Path, *, allow_inherited: bool = False) -> bool:
    """Return whether *path* has exactly the private publication DACL.

    Stays read-only, using native ACL APIs. Every ACE must be a non-inherited
    allow for the current user, SYSTEM, or administrators. The owner must also
    belong to that set, since an owner can replace a restrictive DACL.
    ``allow_inherited`` also accepts private ACEs inherited by new SQLite side
    files from an already restricted parent.
    """
    if os.name != "nt":
        return True
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    owner = ctypes.c_void_p()
    result = advapi32.GetNamedSecurityInfoW(
        str(path),
        1,  # SE_FILE_OBJECT
        0x00000005,  # OWNER + DACL_SECURITY_INFORMATION
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result:
        raise OSError(result, ctypes.FormatError(result), path)
    try:
        if not dacl.value or not owner.value:
            return False
        allowed = {
            windows_current_user_sid(),
            "S-1-5-18",
            "S-1-5-32-544",
        }
        rendered = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(owner, ctypes.byref(rendered)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return (
                rendered.value in allowed
                and _restricted_dacl_principals(dacl, allow_inherited=allow_inherited)
                == allowed
            )
        finally:
            kernel32.LocalFree(rendered)
    finally:
        kernel32.LocalFree(descriptor)


def _owner_only_bits(*, directory: bool) -> int:
    return 0o700 if directory else 0o600


def owner_only_mode(path: Path) -> int:
    """Return the POSIX mode that restricts *path* to its owner.

    A directory needs its execute bit to stay traversable, so the two kinds are
    not interchangeable: ``0o600`` on a directory strips traversal and makes
    everything beneath it unreachable, while ``chmod`` itself still reports
    success. The failure therefore surfaces far from its cause, which is why the
    distinction is decided here rather than at each call site.
    """
    return _owner_only_bits(directory=path.is_dir())


def harden_credential_path(path: Path) -> None:
    """Restrict *path* to its owner: POSIX mode bits, or a private DACL on Windows.

    Covers both files and directories, because callers protect both - a
    credential file, and the state directory whose databases must not be
    readable beside it. Reads back the effective permissions on both platforms,
    so a filesystem that ignores permission changes cannot silently pass.
    """
    if path_is_link_like(path):
        raise OSError(f"refusing to restrict a linked path: {path}")
    if os.name == "posix":
        os.chmod(path, owner_only_mode(path))
    elif os.name == "nt":
        restrict_windows_file(path)
    else:
        raise OSError(f"owner-restricted access is unsupported on {os.name}")
    if not path_is_owner_restricted(path):
        raise OSError(f"could not apply owner-restricted access to {path}")


def _owner_rule_holds(info: os.stat_result, path: Path, *, rule: _OwnerRule) -> bool:
    """Apply *rule* to *info*, the metadata of *path* or of its descriptor.

    The Windows DACL is reachable only by name, so *path* is read there whichever
    object *info* describes. A platform that is neither POSIX nor Windows has no
    rule this module can verify and is never owner-restricted.
    """
    if os.name == "posix":
        if info.st_uid != os.geteuid():
            return False
        if rule is _OwnerRule.CREDENTIAL:
            return not info.st_mode & 0o077
        expected = _owner_only_bits(directory=stat.S_ISDIR(info.st_mode))
        return stat.S_IMODE(info.st_mode) == expected
    if os.name == "nt":
        return windows_file_is_restricted(
            path, allow_inherited=rule is _OwnerRule.STATE
        )
    return False


def path_is_owner_restricted(path: Path) -> bool:
    """Check a real file or directory's effective private permissions.

    This is the state rule, the one :func:`harden_credential_path` applies and
    verifies: exactly ``0o600`` for a file or ``0o700`` for a directory on POSIX,
    and on Windows the private DACL, where private entries inherited from an
    already restricted parent also pass because SQLite creates its side files
    after that parent was hardened. A secret is read under the stricter
    :func:`credential_file_is_owner_restricted` instead. A symlink or junction is
    never owner-restricted; a path that cannot be inspected raises.
    """
    if path_is_link_like(path):
        return False
    info = path.stat(follow_symlinks=False)
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        return False
    return _owner_rule_holds(info, path, rule=_OwnerRule.STATE)


def credential_file_is_owner_restricted(path: Path) -> bool:
    """Return whether *path* is a regular file reachable only by its owner.

    This is the credential rule a secret is read under, and it differs from
    :func:`path_is_owner_restricted` on purpose. POSIX requires the current
    effective user as owner with no group or other access, so a read-only
    ``0o400`` secret qualifies. Windows requires the private DACL with explicit
    entries only, because a file carrying inherited ones was never hardened
    itself and follows whatever its parent is later granted. A non-regular file,
    a symlink, a Windows junction, or a path that cannot be inspected is never
    owner-restricted.
    """
    if path_is_link_like(path):
        return False
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode):
        return False
    return _owner_rule_holds(info, path, rule=_OwnerRule.CREDENTIAL)


def unfollowed_read_flags() -> int:
    """Return the read-only open flags that refuse to traverse a link.

    Declared once because its most important property is a negative one that no
    call site can see locally: ``O_NOFOLLOW`` DOES NOT EXIST ON WINDOWS, where
    ``getattr`` yields zero and the flag silently contributes nothing. A reader
    that opens a planted symlink with these flags on Windows reads straight
    through it.

    The flags are therefore a defence in depth, never the guarantee. What
    actually refuses a link on the shipping platform is the explicit
    stat-by-name and regular-file test that must run BEFORE this open, and the
    descriptor identity confirmation that must run after it. Callers keep both;
    :func:`confirm_opened_secret` is the second half.

    The per-platform extras are absent-safe in the same way and mean nothing
    beyond hygiene here: ``O_CLOEXEC`` keeps a secret out of a forked child on
    POSIX, ``O_BINARY`` suppresses newline translation on Windows.
    """
    return (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_BINARY", 0)
    )


def confirm_opened_secret(
    descriptor: int, *, named: os.stat_result, path: Path
) -> bool:
    """Return whether an open descriptor is the owner-restricted file that was checked.

    Closes the window between inspecting a secret by name and reading it. Every
    property a caller verified about the NAME is re-asked of the DESCRIPTOR it
    actually holds, so a file swapped between the two - the moment a symlink
    attack needs - is caught even where the open could not refuse the swap
    itself.

    Three things are confirmed, and each fails a different substitution: both
    the named and the opened file are regular, so a directory or device
    substituted for either is refused; their device and inode agree, so a
    different file at the same name is refused; and the descriptor is
    owner-restricted under the credential rule, so a file that became reachable
    by another account between the two observations is refused.

    Owner-restriction is asked of the descriptor rather than the name wherever
    the platform allows it, because the name can be re-pointed after the answer
    is given and the descriptor cannot. On Windows the discretionary
    access-control list is only reachable by name, so that one check is
    necessarily by-name and callers keep their own by-name link refusal in front
    of it.

    Args:
        descriptor: An open descriptor for the secret being read.
        named: The pre-open ``lstat`` result the caller validated by name.
        path: The name *descriptor* was opened from, for the Windows list read.

    Returns:
        Whether the descriptor may be read. ``False`` is one outcome - this is
        not the file that was checked - and each caller maps it to its own
        refusal.
    """
    try:
        opened = os.fstat(descriptor)
    except OSError:
        return False
    if not stat.S_ISREG(named.st_mode) or not stat.S_ISREG(opened.st_mode):
        return False
    if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
        return False
    return _owner_rule_holds(opened, path, rule=_OwnerRule.CREDENTIAL)
