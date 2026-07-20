"""Real file-based tests for the one-time migration transaction descriptor.

Every test writes a real descriptor JSON file on disk and drives the production
loader against it. No mock, monkeypatch, stub, skip, or expected failure is used;
rejection is proved by the loader raising :class:`TransactionDescriptorError`
against genuinely malformed, root-inconsistent, range-incompatible, expired,
non-regular, or already-consumed descriptors, and single-use is proved by a real
marker file written to the application home.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ..profile import derive_state_paths
from ..transaction import (
    TransactionDescriptorError,
    consumption_marker_path,
    load_transaction_descriptor,
    mark_transaction_consumed,
    package_migration_range,
)

if TYPE_CHECKING:
    from pathlib import Path

_DIGEST = "a" * 64


def _descriptor_dict(home: Path, **overrides: object) -> dict[str, object]:
    """Build a well-formed descriptor document for application home ``home``."""
    state = derive_state_paths(home)
    packaged = package_migration_range()
    document: dict[str, object] = {
        "descriptor_version": "1",
        "transaction_id": "txn-0001",
        "app_home": str(home),
        "database_path": str(state.database_path),
        "checkpoint_path": str(state.checkpoint_path),
        "generation": {
            "manifest_digest": _DIGEST,
            "component_version": "1.2.3",
        },
        "migration_range": {"base": packaged.base, "head": packaged.head},
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    document.update(overrides)
    return document


def _write(path: Path, document: dict[str, object]) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_valid_descriptor_loads(tmp_path: Path) -> None:
    """A well-formed, current, unconsumed descriptor validates fully."""
    app_home = tmp_path / "app"
    descriptor_path = _write(tmp_path / "txn.json", _descriptor_dict(app_home))

    validated = load_transaction_descriptor(descriptor_path)

    state = derive_state_paths(app_home)
    assert validated.descriptor.transaction_id == "txn-0001"
    assert validated.state.database_path == state.database_path
    assert validated.consumption_marker == consumption_marker_path(validated.descriptor)


def test_relative_app_home_is_rejected(tmp_path: Path) -> None:
    """A launch-relative application home is refused."""
    descriptor_path = _write(
        tmp_path / "txn.json",
        _descriptor_dict(tmp_path / "app", app_home="relative/app"),
    )
    with pytest.raises(TransactionDescriptorError, match="absolute"):
        load_transaction_descriptor(descriptor_path)


def test_database_root_mismatch_is_rejected(tmp_path: Path) -> None:
    """A database path outside the profile derivation is refused."""
    app_home = tmp_path / "app"
    descriptor_path = _write(
        tmp_path / "txn.json",
        _descriptor_dict(app_home, database_path=str(tmp_path / "elsewhere.db")),
    )
    with pytest.raises(TransactionDescriptorError, match="database path"):
        load_transaction_descriptor(descriptor_path)


def test_checkpoint_root_mismatch_is_rejected(tmp_path: Path) -> None:
    """A checkpoint path outside the profile derivation is refused."""
    app_home = tmp_path / "app"
    descriptor_path = _write(
        tmp_path / "txn.json",
        _descriptor_dict(app_home, checkpoint_path=str(tmp_path / "cp.db")),
    )
    with pytest.raises(TransactionDescriptorError, match="checkpoint path"):
        load_transaction_descriptor(descriptor_path)


def test_incompatible_migration_range_is_rejected(tmp_path: Path) -> None:
    """A claimed range that does not match the packaged graph is refused."""
    app_home = tmp_path / "app"
    descriptor_path = _write(
        tmp_path / "txn.json",
        _descriptor_dict(
            app_home, migration_range={"base": "0001", "head": "9999_future"}
        ),
    )
    with pytest.raises(TransactionDescriptorError, match="migration range"):
        load_transaction_descriptor(descriptor_path)


def test_expired_descriptor_is_rejected(tmp_path: Path) -> None:
    """A descriptor past its expiry instant is refused."""
    app_home = tmp_path / "app"
    descriptor_path = _write(
        tmp_path / "txn.json",
        _descriptor_dict(
            app_home,
            expires_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        ),
    )
    with pytest.raises(TransactionDescriptorError, match="expired"):
        load_transaction_descriptor(descriptor_path)


def test_malformed_document_is_rejected(tmp_path: Path) -> None:
    """A non-JSON descriptor is refused."""
    descriptor_path = tmp_path / "txn.json"
    descriptor_path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(TransactionDescriptorError, match="JSON"):
        load_transaction_descriptor(descriptor_path)


def test_non_regular_descriptor_is_rejected(tmp_path: Path) -> None:
    """A descriptor path that is a directory is refused fail-closed."""
    descriptor_path = tmp_path / "txn.json"
    descriptor_path.mkdir()
    with pytest.raises(TransactionDescriptorError, match="regular file"):
        load_transaction_descriptor(descriptor_path)


def test_consumed_transaction_cannot_be_revalidated(tmp_path: Path) -> None:
    """Once consumed, reloading the same descriptor is rejected as already spent."""
    app_home = tmp_path / "app"
    descriptor_path = _write(tmp_path / "txn.json", _descriptor_dict(app_home))

    validated = load_transaction_descriptor(descriptor_path)
    mark_transaction_consumed(validated)

    assert validated.consumption_marker.is_file()
    with pytest.raises(TransactionDescriptorError, match="already been consumed"):
        load_transaction_descriptor(descriptor_path)


def test_double_consume_is_rejected(tmp_path: Path) -> None:
    """Marking an already-consumed transaction again fails closed."""
    app_home = tmp_path / "app"
    descriptor_path = _write(tmp_path / "txn.json", _descriptor_dict(app_home))
    validated = load_transaction_descriptor(descriptor_path)
    mark_transaction_consumed(validated)

    with pytest.raises(TransactionDescriptorError, match="concurrently"):
        mark_transaction_consumed(validated)
