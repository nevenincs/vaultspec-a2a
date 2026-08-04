"""Cross-platform owner-restriction primitives for local credential files.

Single authority for two questions asked of every local secret file this product
writes or reads: "make this file reachable only by its owner" and "is this file
owner-restricted?". The answer spans POSIX permission bits and Windows discretionary
access-control lists (DACLs). The gateway discovery credential and the desktop
attach, ownership, and worker-interprocess-communication (IPC) credentials all
protect a local secret with the same guarantee, so the native Windows ACL machinery
lives here once rather than being restated in each consumer.

The Windows helpers stay read-only where they inspect and use only native ACL APIs
where they mutate; no third-party dependency is required. On POSIX the guarantee is
mode ``0o600`` owned by the current effective user with no group or other access.
"""

from __future__ import annotations

import ctypes
import os
import stat
import subprocess
from csv import reader as csv_reader
from functools import cache
from pathlib import Path

__all__ = [
    "confirm_opened_secret",
    "credential_file_is_owner_restricted",
    "harden_credential_path",
    "owner_only_mode",
    "restrict_windows_file",
    "unfollowed_read_flags",
    "windows_current_user_sid",
    "windows_file_is_restricted",
]


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


def windows_file_is_restricted(path: Path) -> bool:
    """Return whether *path* has exactly the private publication DACL.

    Stays read-only, using native ACL APIs. Every ACE must be a non-inherited
    allow for the current user, SYSTEM, or administrators.
    """
    if os.name != "nt":
        return True
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    result = advapi32.GetNamedSecurityInfoW(
        str(path),
        1,  # SE_FILE_OBJECT
        0x00000004,  # DACL_SECURITY_INFORMATION
        None,
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result:
        raise OSError(result, ctypes.FormatError(result), path)
    try:
        if not dacl.value:
            return False
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
            if header.ace_type != 0 or header.ace_flags & 0x10:
                return False
            ace_address = ace.value
            if ace_address is None:
                return False
            sid = ctypes.c_void_p(ace_address + ctypes.sizeof(_AceHeader) + 4)
            rendered = ctypes.c_wchar_p()
            if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(rendered)):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if rendered.value is None:
                    return False
                principals.add(rendered.value)
            finally:
                kernel32.LocalFree(rendered)
        return principals == {
            windows_current_user_sid(),
            "S-1-5-18",
            "S-1-5-32-544",
        }
    finally:
        kernel32.LocalFree(descriptor)


def owner_only_mode(path: Path) -> int:
    """Return the POSIX mode that restricts *path* to its owner.

    A directory needs its execute bit to stay traversable, so the two kinds are
    not interchangeable: ``0o600`` on a directory strips traversal and makes
    everything beneath it unreachable, while ``chmod`` itself still reports
    success. The failure therefore surfaces far from its cause, which is why the
    distinction is decided here rather than at each call site.
    """
    return 0o700 if path.is_dir() else 0o600


def harden_credential_path(path: Path) -> None:
    """Restrict *path* to its owner: POSIX mode bits, or a private DACL on Windows.

    Covers both files and directories, because callers protect both - a
    credential file, and the state directory whose databases must not be
    readable beside it. Fails closed on Windows if the applied DACL does not read
    back as owner-restricted, so a caller never trusts a path it could not
    actually protect.
    """
    if os.name == "posix":
        os.chmod(path, owner_only_mode(path))
        return
    restrict_windows_file(path)
    if not windows_file_is_restricted(path):
        raise OSError(f"could not apply an owner-restricted DACL to {path}")


def credential_file_is_owner_restricted(path: Path) -> bool:
    """Return whether *path* is a regular file reachable only by its owner.

    POSIX requires the current effective user as owner with no group or other
    access; Windows requires the private-DACL predicate. A non-regular file, a
    symlink, or a Windows junction is never owner-restricted.
    """
    if path.is_symlink() or path.is_junction():
        return False
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode):
        return False
    if os.name == "posix":
        return info.st_uid == os.geteuid() and not (info.st_mode & 0o077)
    return windows_file_is_restricted(path)


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
    owner-restricted, so a file that became reachable by another account between
    the two observations is refused.

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
    if os.name == "posix":
        return opened.st_uid == os.geteuid() and not (opened.st_mode & 0o077)
    return windows_file_is_restricted(path)
