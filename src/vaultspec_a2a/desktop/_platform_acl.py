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
    "credential_file_is_owner_restricted",
    "harden_credential_file",
    "restrict_windows_file",
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
    completed = subprocess.run(
        [_windows_system_executable("whoami.exe"), "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
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


def harden_credential_file(path: Path) -> None:
    """Restrict *path* to its owner: ``0o600`` on POSIX, a private DACL on Windows.

    Fails closed on Windows if the applied DACL does not read back as owner-
    restricted so a caller never trusts a file it could not actually protect.
    """
    if os.name == "posix":
        os.chmod(path, 0o600)
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
