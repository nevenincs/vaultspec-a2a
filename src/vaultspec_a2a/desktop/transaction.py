"""One-time desktop migration transaction descriptor and its validation.

The dashboard's external updater never migrates a live desktop store in place.
After quiescence it supplies a typed, file-based, owner-restricted *transaction
descriptor* that authorises exactly one staged-generation migration. This module
is the single authority for that descriptor: it defines the strict schema and the
fail-closed validation the migration entrypoint runs before any lifecycle
mutation.

A descriptor is honoured only when every fact holds: it is well-formed and
owner-restricted on disk, its declared state roots match the desktop profile's
own derivation from the application home, its claimed Alembic migration range
matches the package's packaged migration graph, it has not expired, and its
single-use consumption marker does not already exist. Any failure raises a typed
:class:`TransactionDescriptorError`; nothing is migrated on a rejected descriptor.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from ..database.migrate import migration_script_location
from .contract import MigrationRange
from .profile import DesktopProfileError, DesktopStatePaths, derive_state_paths

__all__ = [
    "StagedGenerationIdentity",
    "TransactionDescriptor",
    "TransactionDescriptorError",
    "ValidatedTransaction",
    "consumption_marker_path",
    "load_transaction_descriptor",
    "mark_transaction_consumed",
    "package_migration_range",
]

DESCRIPTOR_VERSION: Final = "1"
_MAX_DESCRIPTOR_BYTES: Final = 1 << 16
_CONSUMED_SUFFIX: Final = ".consumed"

HexDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
TransactionId = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
]


class TransactionDescriptorError(ValueError):
    """A migration transaction descriptor is malformed, unauthorised, or spent.

    Raised for every fail-closed rejection: a missing or non-regular descriptor
    file, group- or world-writable permissions, a malformed document, state roots
    that do not match the desktop profile derivation, a claimed migration range
    that does not match the packaged graph, an expired descriptor, or a
    single-use marker that already exists. The message names the offending fact.
    """


class StagedGenerationIdentity(BaseModel):
    """Identity of the staged A2A generation the migration targets.

    Binds the descriptor to one component generation by its manifest digest so an
    updater cannot replay a descriptor against a different staged capsule.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_digest: HexDigest = Field(
        description="SHA-256 digest of the staged generation's component manifest."
    )
    component_version: str = Field(
        min_length=1,
        max_length=64,
        description="Version string of the staged A2A distribution.",
    )


class TransactionDescriptor(BaseModel):
    """The typed one-time migration authorisation supplied by the updater."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    descriptor_version: Literal["1"] = Field(
        description="Descriptor grammar version; only '1' is accepted."
    )
    transaction_id: TransactionId = Field(
        description="Opaque single-use identifier for this migration transaction."
    )
    app_home: Path = Field(
        description="Absolute desktop application home the migration targets."
    )
    database_path: Path = Field(
        description="Explicit primary database path within the application home."
    )
    checkpoint_path: Path = Field(
        description="Explicit checkpoint database path within the application home."
    )
    generation: StagedGenerationIdentity = Field(
        description="Identity of the staged generation this descriptor authorises."
    )
    migration_range: MigrationRange = Field(
        description="Alembic base/head revision range the migration claims to apply."
    )
    expires_at: AwareDatetime = Field(
        description="Timezone-aware instant after which the descriptor is invalid."
    )


@dataclass(frozen=True, slots=True)
class ValidatedTransaction:
    """A descriptor proven authorised, with its derived state and marker paths."""

    descriptor: TransactionDescriptor
    state: DesktopStatePaths
    consumption_marker: Path


def package_migration_range() -> MigrationRange:
    """Return the packaged Alembic migration graph's base and head revisions."""
    from alembic.script import ScriptDirectory

    try:
        script = ScriptDirectory(str(migration_script_location()))
        heads = script.get_heads()
        bases = script.get_bases()
    except Exception as exc:
        raise TransactionDescriptorError(
            "cannot read the packaged Alembic migration graph; reinstall "
            "vaultspec-a2a from a complete distribution."
        ) from exc
    if len(heads) != 1 or len(bases) != 1:
        raise TransactionDescriptorError(
            "the packaged Alembic migration graph must have exactly one base and "
            "one head."
        )
    return MigrationRange(base=bases[0], head=heads[0])


def consumption_marker_path(descriptor: TransactionDescriptor) -> Path:
    """Return the durable single-use marker path for ``descriptor``.

    The marker lives under the application home's receipts directory, keyed by
    transaction id, so a descriptor cannot be replayed even if its source file is
    recreated after use.
    """
    state = derive_state_paths(descriptor.app_home)
    return (
        state.receipts_dir
        / f"migration-transaction-{descriptor.transaction_id}{_CONSUMED_SUFFIX}"
    )


def _read_descriptor_bytes(path: Path) -> bytes:
    """Read the descriptor file fail-closed, enforcing owner-restriction."""
    try:
        info = path.lstat()
    except OSError as exc:
        raise TransactionDescriptorError(
            f"transaction descriptor {path} is not accessible."
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise TransactionDescriptorError(
            f"transaction descriptor {path} must be a regular file."
        )
    # On POSIX an owner-restricted descriptor must not be group- or world-writable;
    # a loose descriptor could be forged by another local principal. Windows ACL
    # enforcement is owned by the credential-boundary work, not this module.
    if os.name == "posix" and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise TransactionDescriptorError(
            f"transaction descriptor {path} must not be group- or world-writable."
        )
    if info.st_size > _MAX_DESCRIPTOR_BYTES:
        raise TransactionDescriptorError(
            f"transaction descriptor {path} exceeds its size bound."
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise TransactionDescriptorError(
            f"transaction descriptor {path} cannot be read."
        ) from exc


def _parse_descriptor(payload: bytes) -> TransactionDescriptor:
    try:
        document = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TransactionDescriptorError(
            "transaction descriptor is not valid UTF-8 JSON."
        ) from exc
    try:
        return TransactionDescriptor.model_validate(document)
    except ValidationError as exc:
        raise TransactionDescriptorError(
            f"transaction descriptor is malformed: {exc.error_count()} error(s)."
        ) from exc


def _validate_roots(descriptor: TransactionDescriptor) -> DesktopStatePaths:
    """Validate the declared roots match the desktop profile's own derivation."""
    try:
        state = derive_state_paths(descriptor.app_home)
    except DesktopProfileError as exc:
        raise TransactionDescriptorError(str(exc)) from exc

    declared_home = Path(os.path.normpath(descriptor.app_home))
    if declared_home != state.app_home:
        raise TransactionDescriptorError(
            f"transaction descriptor application home {descriptor.app_home} is not "
            "canonical."
        )
    if Path(os.path.normpath(descriptor.database_path)) != state.database_path:
        raise TransactionDescriptorError(
            f"transaction descriptor database path {descriptor.database_path} does "
            f"not match the profile derivation {state.database_path}."
        )
    if Path(os.path.normpath(descriptor.checkpoint_path)) != state.checkpoint_path:
        raise TransactionDescriptorError(
            f"transaction descriptor checkpoint path {descriptor.checkpoint_path} "
            f"does not match the profile derivation {state.checkpoint_path}."
        )
    return state


def _validate_migration_range(descriptor: TransactionDescriptor) -> None:
    packaged = package_migration_range()
    claimed = descriptor.migration_range
    if claimed.base != packaged.base or claimed.head != packaged.head:
        raise TransactionDescriptorError(
            f"transaction descriptor migration range {claimed.base}..{claimed.head} "
            f"does not match the packaged range {packaged.base}..{packaged.head}."
        )


def load_transaction_descriptor(
    path: Path, *, now: datetime | None = None
) -> ValidatedTransaction:
    """Load and fully validate a one-time migration transaction descriptor.

    Args:
        path: Filesystem path to the descriptor JSON document.
        now: Reference instant for expiry evaluation; defaults to the current UTC
            time. Must be timezone-aware when provided.

    Returns:
        A :class:`ValidatedTransaction` binding the parsed descriptor to its
        derived state paths and durable consumption marker.

    Raises:
        TransactionDescriptorError: If the descriptor is missing, not
            owner-restricted, malformed, root-inconsistent, range-incompatible,
            expired, or already consumed.
    """
    reference = now if now is not None else datetime.now(UTC)
    if reference.tzinfo is None:
        raise TransactionDescriptorError(
            "expiry reference instant must be timezone-aware."
        )

    descriptor = _parse_descriptor(_read_descriptor_bytes(path))
    if descriptor.descriptor_version != DESCRIPTOR_VERSION:
        raise TransactionDescriptorError(
            f"unsupported descriptor version {descriptor.descriptor_version!r}."
        )
    state = _validate_roots(descriptor)
    _validate_migration_range(descriptor)

    if descriptor.expires_at <= reference:
        raise TransactionDescriptorError(
            f"transaction descriptor expired at {descriptor.expires_at.isoformat()}."
        )

    marker = consumption_marker_path(descriptor)
    if marker.exists():
        raise TransactionDescriptorError(
            f"transaction {descriptor.transaction_id} has already been consumed."
        )
    return ValidatedTransaction(
        descriptor=descriptor, state=state, consumption_marker=marker
    )


def mark_transaction_consumed(transaction: ValidatedTransaction) -> None:
    """Durably record that a validated transaction has been consumed.

    Writes the single-use marker atomically and fails closed if it already
    exists, so a race can never let two migrations claim the same descriptor.
    """
    marker = transaction.consumption_marker
    marker.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat()
    try:
        with marker.open("x", encoding="utf-8") as handle:
            handle.write(
                f"{transaction.descriptor.transaction_id} consumed at {stamp}\n"
            )
    except FileExistsError as exc:
        raise TransactionDescriptorError(
            f"transaction {transaction.descriptor.transaction_id} was consumed "
            "concurrently."
        ) from exc
