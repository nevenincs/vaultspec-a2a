"""Split desktop credential planes: attach control, ownership, worker IPC.

The desktop product profile authenticates three disjoint trust planes, each with
its own owner-restricted file beneath the application home's credentials directory:

* **attach control** - created by the dashboard, read by the gateway, presented on
  every versioned control verb, product application programming interface (API)
  call, event stream, and terminal settlement callback.
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

import secrets
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..utils import path_is_link_like
from ..utils.atomic_write import atomic_write_text
from ._filesystem_authority import PrivateFileError, read_private_file
from ._platform_acl import harden_credential_path

__all__ = [
    "ATTACH_CREDENTIAL_NAME",
    "MAX_CREDENTIAL_BYTES",
    "OWNERSHIP_CAPABILITY_NAME",
    "WORKER_IPC_CREDENTIAL_NAME",
    "CredentialError",
    "DesktopCredentialPaths",
    "create_worker_ipc_credential",
    "credential_paths",
    "load_attach_credential",
    "load_ownership_capability",
]

ATTACH_CREDENTIAL_NAME = "attach.cred"
OWNERSHIP_CAPABILITY_NAME = "ownership.cap"
WORKER_IPC_CREDENTIAL_NAME = "worker-ipc.cred"

# A credential is an opaque high-entropy token. These bounds reject an empty or
# truncated file and a pathologically large one before the bytes are trusted; the
# charset admits the URL-safe and hex token alphabets this product mints without
# admitting whitespace or control characters that would signal a malformed file.
_MIN_CREDENTIAL_CHARS = 16
MAX_CREDENTIAL_BYTES = 4096
_ALLOWED_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-+/="
)
# The gateway mints a 256-bit worker IPC secret; 32 bytes rendered as hex.
_WORKER_IPC_ENTROPY_BYTES = 32


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

    The file is read through the private-file reader, which owns every
    filesystem refusal: a leased real parent, a regular non-link singly linked
    file, owner-restriction (POSIX mode and ownership or the Windows private
    DACL), the size bound, and a descriptor confirmed to be the file inspected
    by name. This plane adds only the UTF-8 decode and the token shape.
    """
    try:
        raw = read_private_file(path, max_bytes=MAX_CREDENTIAL_BYTES)
    except PrivateFileError as exc:
        raise CredentialError(f"{plane.value} credential file {exc.reason}") from exc
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
    if path_is_link_like(target):
        raise CredentialError("worker_ipc credential path is a link")

    # Published through the project's audited write-and-rename, which is the only
    # copy of that discipline: a concurrent reader never observes a partial file,
    # and an interrupted mint removes its own temporary rather than stranding a
    # live secret beside the credential. The owner-restriction travels as a
    # callable because it is not expressible as permission bits alone - on Windows
    # it is a discretionary access-control list - and it is applied to the
    # temporary before the rename, so the secret is never reachable by another
    # local principal under its real name, not even for the width of the rename.
    atomic_write_text(target, secret, mode=0o600, harden=harden_credential_path)
    return secret
