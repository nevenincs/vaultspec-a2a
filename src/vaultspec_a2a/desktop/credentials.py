"""Split desktop credential planes: attach control, ownership, worker IPC.

The desktop product profile authenticates three disjoint trust planes, each with
its own owner-restricted file beneath the application home's credentials directory:

* **attach control** - created by the dashboard, read by the gateway, presented on
  every versioned control verb, product application programming interface (API)
  call, event WebSocket, and terminal settlement callback.
* **ownership capability** - created by the dashboard and bound to the install
  receipt, read by the gateway, additionally required on receipt-bound lifecycle
  operations such as administrative shutdown. Discovery never references it.
* **worker interprocess-communication (IPC)** - created by the gateway per boot,
  private to the gateway-worker pair, never exposed to or required by the dashboard.

This module is the single authority for that split. It validates the two
dashboard-created files fail-closed (a regular, owner-restricted, bounded,
well-formed secret) and mints the gateway-owned worker IPC secret under the same
owner-restriction guarantee. Every rejection raises a typed
:class:`CredentialError`; no credential value is ever placed in a message, log, or
exception argument.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import stat
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..artifacts import ArtifactDeclaration, RetentionDisposition
from ._platform_acl import (
    credential_file_is_owner_restricted,
    harden_credential_path,
)

__all__ = [
    "ARTIFACT_DECLARATIONS",
    "ATTACH_CREDENTIAL_NAME",
    "OWNERSHIP_CAPABILITY_NAME",
    "WORKER_IPC_CREDENTIAL_DECLARATION",
    "WORKER_IPC_CREDENTIAL_NAME",
    "CredentialError",
    "CredentialPlane",
    "DesktopCredentialPaths",
    "create_worker_ipc_credential",
    "credential_paths",
    "load_attach_credential",
    "load_ownership_capability",
]

ATTACH_CREDENTIAL_NAME = "attach.cred"
OWNERSHIP_CAPABILITY_NAME = "ownership.cap"
WORKER_IPC_CREDENTIAL_NAME = "worker-ipc.cred"

# Only the worker IPC file is declared here: the other two planes are created by
# the dashboard and this module merely validates them, so their lifetime is not
# this project's to state. The disk cost is nil - one fixed-name file, replaced
# rather than accumulated - which is exactly why the interesting part of this
# declaration is the part that is NOT enforced: a live secret stays readable on
# disk after the gateway that minted it exits.
WORKER_IPC_CREDENTIAL_DECLARATION = ArtifactDeclaration(
    name="worker-ipc-credential",
    root=f"<desktop_credentials_dir>/{WORKER_IPC_CREDENTIAL_NAME}",
    owner="desktop.credentials",
    disposition=RetentionDisposition.SESSION_SCOPED,
    mechanism=(
        "replaced wholesale on every mint, so a boot always owns its own secret "
        "and the file never multiplies; a failed mint removes its own temporary "
        "rather than stranding a second secret. NOTHING removes the file on "
        "shutdown, so the last boot's secret remains at rest, owner-restricted, "
        "until the next boot overwrites it"
    ),
)

ARTIFACT_DECLARATIONS: tuple[ArtifactDeclaration, ...] = (
    WORKER_IPC_CREDENTIAL_DECLARATION,
)

# A credential is an opaque high-entropy token. These bounds reject an empty or
# truncated file and a pathologically large one before the bytes are trusted; the
# charset admits the URL-safe and hex token alphabets this product mints without
# admitting whitespace or control characters that would signal a malformed file.
_MIN_CREDENTIAL_CHARS = 16
_MAX_CREDENTIAL_BYTES = 4096
_ALLOWED_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-+/="
)
# The gateway mints a 256-bit worker IPC secret; 32 bytes rendered as hex.
_WORKER_IPC_ENTROPY_BYTES = 32

# How long to ride out a transient Windows sharing violation on the rename that
# publishes the minted secret. ``os.replace`` is atomic, but on Windows a reader
# holding the target open can briefly deny it, and this file is read by the
# gateway-worker pair while a later boot may be publishing over it.
#
# This mirrors, rather than calls, the lifecycle package's audited writer. That
# writer takes text and optional permission bits and renames immediately after
# the fsync; this mint has to apply the owner-restricting access-control list to
# the temporary file *between* the fsync and the rename, so the secret is never
# reachable by another local principal - not even for the width of the rename -
# and on Windows those bits are a discretionary access-control list rather than
# mode bits the shared writer could pass through. It also opens the temporary
# with ``O_NOFOLLOW``, which that writer does not. Adding a pre-rename callback
# to the shared writer for this single caller would trade one duplicated loop
# for a general-purpose seam nothing else wants.
_REPLACE_RETRY_SECONDS = 2.0
_REPLACE_RETRY_INTERVAL = 0.01


class CredentialError(ValueError):
    """A credential file is missing, not owner-restricted, or malformed.

    Raised for every fail-closed rejection: an absent or non-regular file, a
    symlink or junction, a file another local principal could write, a file
    outside the size bound, or content that is empty or not a well-formed token.
    The message names the plane and the offending fact but never the secret.
    """


class CredentialPlane(StrEnum):
    """The three disjoint desktop credential trust planes."""

    ATTACH = "attach"
    OWNERSHIP = "ownership"
    WORKER_IPC = "worker_ipc"


@dataclass(frozen=True, slots=True)
class DesktopCredentialPaths:
    """The three credential file paths beneath one credentials directory.

    Pure path derivation: constructing this performs no filesystem access and
    reads no secret. The gateway consumes the paths at boot to load the
    dashboard-created planes and mint the worker IPC plane.
    """

    credentials_dir: Path
    attach_path: Path
    ownership_path: Path
    worker_ipc_path: Path


def credential_paths(credentials_dir: Path) -> DesktopCredentialPaths:
    """Derive the three credential paths beneath *credentials_dir*.

    This is the single authority for the credential-file layout; the settings
    profile and the gateway both resolve their credential paths through it rather
    than restating the filenames.
    """
    directory = Path(credentials_dir)
    return DesktopCredentialPaths(
        credentials_dir=directory,
        attach_path=directory / ATTACH_CREDENTIAL_NAME,
        ownership_path=directory / OWNERSHIP_CAPABILITY_NAME,
        worker_ipc_path=directory / WORKER_IPC_CREDENTIAL_NAME,
    )


def _validate_token(text: str, *, plane: CredentialPlane) -> str:
    """Validate that *text* is a well-formed credential token or fail closed."""
    token = text.strip()
    if not token:
        raise CredentialError(f"{plane.value} credential file is empty")
    if len(token) < _MIN_CREDENTIAL_CHARS:
        raise CredentialError(
            f"{plane.value} credential is shorter than the {_MIN_CREDENTIAL_CHARS}-"
            "character minimum"
        )
    if any(char not in _ALLOWED_CHARS for char in token):
        raise CredentialError(
            f"{plane.value} credential contains characters outside the token alphabet"
        )
    return token


def _read_owner_restricted_secret(path: Path, *, plane: CredentialPlane) -> str:
    """Read one owner-restricted credential file fail-closed and return its token.

    Enforces, in order: a regular non-link file, owner-restriction (POSIX mode and
    ownership or the Windows private DACL), a bounded size, and a well-formed token.
    The file is opened without following a symlink so a swapped link cannot redirect
    the read, and the opened descriptor's identity is confirmed to match the
    validated name.
    """
    try:
        named = path.lstat()
    except OSError as exc:
        raise CredentialError(
            f"{plane.value} credential file is not accessible"
        ) from exc
    if not stat.S_ISREG(named.st_mode):
        raise CredentialError(f"{plane.value} credential file is not a regular file")
    if not credential_file_is_owner_restricted(path):
        raise CredentialError(f"{plane.value} credential file is not owner-restricted")
    if named.st_size > _MAX_CREDENTIAL_BYTES:
        raise CredentialError(f"{plane.value} credential file exceeds its size bound")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CredentialError(
            f"{plane.value} credential file cannot be opened"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            named.st_dev,
            named.st_ino,
        ):
            raise CredentialError(
                f"{plane.value} credential file changed identity while opening"
            )
        raw = os.read(descriptor, _MAX_CREDENTIAL_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > _MAX_CREDENTIAL_BYTES:
        raise CredentialError(f"{plane.value} credential file exceeds its size bound")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CredentialError(
            f"{plane.value} credential file is not valid UTF-8"
        ) from exc
    return _validate_token(text, plane=plane)


def load_attach_credential(credentials_dir: Path) -> str:
    """Load and validate the dashboard-created attach-control credential."""
    paths = credential_paths(credentials_dir)
    return _read_owner_restricted_secret(
        paths.attach_path, plane=CredentialPlane.ATTACH
    )


def load_ownership_capability(credentials_dir: Path) -> str:
    """Load and validate the dashboard-created receipt-bound ownership capability."""
    paths = credential_paths(credentials_dir)
    return _read_owner_restricted_secret(
        paths.ownership_path, plane=CredentialPlane.OWNERSHIP
    )


def create_worker_ipc_credential(credentials_dir: Path) -> str:
    """Mint the gateway-owned worker IPC credential under owner-restriction.

    Generates a fresh 256-bit secret per call, writes it to a private regular file
    beneath *credentials_dir*, hardens the file to owner-only access, and returns
    the secret. An existing file is replaced so a boot always owns its own IPC
    secret. The directory is created owner-restricted if absent. The secret is
    never logged, and a mint that does not complete removes its temporary file
    rather than stranding a live secret beside the credential.
    """
    directory = Path(credentials_dir)
    directory.mkdir(parents=True, exist_ok=True)
    harden_credential_path(directory)

    paths = credential_paths(directory)
    secret = secrets.token_hex(_WORKER_IPC_ENTROPY_BYTES)
    target = paths.worker_ipc_path
    if target.is_symlink() or target.is_junction():
        raise CredentialError("worker_ipc credential path is a link")

    # Write to a private per-process temp then atomically replace, so a concurrent
    # reader never observes a partially written or world-readable secret.
    tmp = target.with_name(f".{WORKER_IPC_CREDENTIAL_NAME}.{os.getpid()}.tmp")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_TRUNC
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
    )
    try:
        descriptor = os.open(tmp, flags, 0o600)
        try:
            os.write(descriptor, secret.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        harden_credential_path(tmp)
        _replace_with_retry(tmp, target)
    except BaseException:
        # Every failure path, ``KeyboardInterrupt`` and ``SystemExit`` included:
        # an interrupted mint must never be the one case that leaves a live
        # secret sitting in a temporary file nothing collects.
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
    return secret


def _replace_with_retry(tmp: Path, target: Path) -> None:
    """Rename *tmp* over *target*, riding out a transient sharing violation."""
    deadline = time.monotonic() + _REPLACE_RETRY_SECONDS
    while True:
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(_REPLACE_RETRY_INTERVAL)
