from __future__ import annotations

import errno
import os
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.desktop._filesystem_authority import (
    create_private_file,
    directory_lease,
    publish_no_replace,
    resolve_directory_authority,
)

if TYPE_CHECKING:
    from pathlib import Path


if os.name == "posix":

    def test_named_file_publication_fails_closed(tmp_path: Path) -> None:
        authority = resolve_directory_authority(tmp_path)
        with (
            directory_lease(authority) as lease,
            create_private_file(lease, "private") as source,
        ):
            source.write(b"capsule")
            source.flush()
            os.fsync(source.fileno())
            with pytest.raises(OSError) as raised:
                publish_no_replace(
                    lease,
                    "private",
                    "published",
                    source_fd=source.fileno(),
                )

        assert raised.value.errno == errno.ENOSYS
        assert (tmp_path / "private").read_bytes() == b"capsule"
        assert not (tmp_path / "published").exists()

    def test_named_file_publication_rejects_changed_source_without_lookup(
        tmp_path: Path,
    ) -> None:
        authority = resolve_directory_authority(tmp_path)
        with (
            directory_lease(authority) as lease,
            create_private_file(lease, "private") as source,
        ):
            source.write(b"held")
            source.flush()
            os.fsync(source.fileno())
            os.rename(
                "private",
                "displaced",
                src_dir_fd=lease.dir_fd,
                dst_dir_fd=lease.dir_fd,
            )
            (tmp_path / "private").write_bytes(b"replacement")
            with pytest.raises(OSError) as raised:
                publish_no_replace(
                    lease,
                    "private",
                    "published",
                    source_fd=source.fileno(),
                )

        assert raised.value.errno == errno.ENOSYS
        assert not (tmp_path / "published").exists()
        assert (tmp_path / "private").read_bytes() == b"replacement"
        assert (tmp_path / "displaced").read_bytes() == b"held"

    def test_directory_publication_fails_closed(
        tmp_path: Path,
    ) -> None:
        source_path = tmp_path / "private"
        source_path.mkdir()
        (source_path / "payload").write_bytes(b"capsule")
        root_authority = resolve_directory_authority(tmp_path)
        source_authority = resolve_directory_authority(source_path)

        with (
            directory_lease(root_authority) as root_lease,
            directory_lease(source_authority, publication=True) as source_lease,
            pytest.raises(OSError) as raised,
        ):
            publish_no_replace(
                root_lease,
                "private",
                "published",
                source_authority=source_lease,
            )

        assert raised.value.errno == errno.ENOSYS
        assert (source_path / "payload").read_bytes() == b"capsule"
        assert not (tmp_path / "published").exists()

    def test_directory_publication_refuses_existing_destination(
        tmp_path: Path,
    ) -> None:
        source_path = tmp_path / "private"
        source_path.mkdir()
        destination_path = tmp_path / "published"
        destination_path.mkdir()
        (destination_path / "existing").write_bytes(b"preserved")
        root_authority = resolve_directory_authority(tmp_path)
        source_authority = resolve_directory_authority(source_path)

        with (
            directory_lease(root_authority) as root_lease,
            directory_lease(source_authority, publication=True) as source_lease,
            pytest.raises(OSError) as raised,
        ):
            publish_no_replace(
                root_lease,
                "private",
                "published",
                source_authority=source_lease,
            )

        assert raised.value.errno == errno.ENOSYS
        assert source_path.is_dir()
        assert (destination_path / "existing").read_bytes() == b"preserved"
