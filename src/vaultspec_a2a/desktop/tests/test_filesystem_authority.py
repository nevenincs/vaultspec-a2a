from __future__ import annotations

import ctypes
import errno
import os
from typing import TYPE_CHECKING

import pytest

from ...desktop._filesystem_authority import (
    _ERROR_SHARING_VIOLATION,
    _create_file_w,
    _windows_error,
    _windows_library,
    assert_directory_authority,
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


if os.name == "nt":
    # The whole of the block above is POSIX-gated, so before these tests this
    # module executed NOTHING on Windows - the platform whose native CreateFileW
    # prototype the module actually declares. These drive both native call sites
    # for real: a mis-declared argtypes slot mis-marshals the access mask,
    # disposition or flags and fails here rather than corrupting a file silently.

    def test_create_file_w_declares_one_seven_slot_prototype() -> None:
        """The prototype is declared once, with CreateFileW's real arity."""
        library = _windows_library()
        create_file = _create_file_w(library)

        assert create_file.argtypes == (
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        )
        assert create_file.restype is ctypes.c_void_p
        # Re-declaring is idempotent: the accessor is the only writer, so two
        # consumers of one library instance cannot disagree about the signature.
        assert _create_file_w(library).argtypes == create_file.argtypes

    def test_directory_lease_opens_a_real_native_handle(tmp_path: Path) -> None:
        """The lease call site: CreateFileW must return a usable directory handle.

        ``assert_directory_authority`` re-reads the handle through
        ``GetFileInformationByHandle`` and compares its file index to the
        identity resolved by name, so a handle opened against the wrong object -
        the observable symptom of a mis-marshalled path or flags argument -
        fails rather than passing silently.
        """
        authority = resolve_directory_authority(tmp_path)
        assert authority.native_handle is None

        with directory_lease(authority) as leased:
            assert leased.native_handle is not None
            assert leased.native_handle not in (0, ctypes.c_void_p(-1).value)
            assert leased.dir_fd is None
            # Proves the handle addresses THIS directory, not some other object.
            assert_directory_authority(leased)
            assert leased.identity == authority.identity

    def test_private_file_claim_honours_create_new_disposition(
        tmp_path: Path,
    ) -> None:
        """The file call site: CREATE_NEW must land in the disposition slot.

        If the disposition argument were marshalled into the wrong slot the
        second claim would silently reopen (or truncate) the first file instead
        of failing, so the ``FileExistsError`` is the marshalling assertion.
        """
        authority = resolve_directory_authority(tmp_path)
        with directory_lease(authority) as leased:
            with create_private_file(leased, "claimed") as handle:
                handle.write(b"private-payload")
                handle.flush()
                os.fsync(handle.fileno())

            # The read/write access mask really was granted.
            assert (tmp_path / "claimed").read_bytes() == b"private-payload"

            with pytest.raises(FileExistsError) as raised:
                create_private_file(leased, "claimed")

        assert raised.value.errno == errno.EEXIST
        assert (tmp_path / "claimed").read_bytes() == b"private-payload"

    def test_private_file_publishes_the_exact_held_handle(tmp_path: Path) -> None:
        """Both call sites in one flow, ending in a rename of the live handle.

        Publication renames the handle ``create_private_file`` returned, which
        only succeeds when the DELETE bit was marshalled into that call's access
        mask - the one bit distinguishing the two call sites' masks.
        """
        authority = resolve_directory_authority(tmp_path)
        with (
            directory_lease(authority, publication=True) as leased,
            create_private_file(leased, "staged") as source,
        ):
            source.write(b"capsule")
            source.flush()
            os.fsync(source.fileno())
            publish_no_replace(
                leased,
                "staged",
                "published",
                source_fd=source.fileno(),
            )

        assert (tmp_path / "published").read_bytes() == b"capsule"
        assert not (tmp_path / "staged").exists()

    def test_publication_refuses_an_existing_destination(tmp_path: Path) -> None:
        """``replace_if_exists = 0`` still holds after the prototype rehoming."""
        (tmp_path / "published").write_bytes(b"preserved")
        authority = resolve_directory_authority(tmp_path)
        with (
            directory_lease(authority, publication=True) as leased,
            create_private_file(leased, "staged") as source,
        ):
            source.write(b"capsule")
            source.flush()
            os.fsync(source.fileno())
            with pytest.raises(FileExistsError) as raised:
                publish_no_replace(
                    leased,
                    "staged",
                    "published",
                    source_fd=source.fileno(),
                )

        assert raised.value.errno == errno.EEXIST
        assert (tmp_path / "published").read_bytes() == b"preserved"


if os.name == "nt":

    def test_a_publication_lease_rides_out_a_peer_holding_the_directory(
        tmp_path: Path,
    ) -> None:
        """A transient sharing violation is waited out, not raised.

        A publication lease additionally requests DELETE, which a concurrent
        holder of the same directory need not be sharing. Before this was ridden
        out, one lost race raised immediately - and because this lease guards the
        service-discovery heartbeat, that meant a live gateway silently stopped
        publishing where it could be found for the rest of its life, on any
        machine where a second process touched the directory. That is the normal
        case here, not an exotic one.

        The peer is a real conflicting Windows handle, opened without sharing
        DELETE, released from a timer while the lease is being attempted. No
        patching: the retry either outlasts a genuine sharing violation or the
        test fails.
        """
        import threading

        library = _windows_library()
        create_file = _create_file_w(library)
        authority = resolve_directory_authority(tmp_path)

        # FILE_SHARE_READ | FILE_SHARE_WRITE, deliberately WITHOUT FILE_SHARE_DELETE,
        # so a publication lease's DELETE request collides with this holder.
        blocker = create_file(
            str(tmp_path),
            0x0080 | 0x0020,
            0x00000001 | 0x00000002,
            None,
            3,
            0x02000000 | 0x00200000,
            None,
        )
        assert blocker not in {None, ctypes.c_void_p(-1).value}, (
            "could not open the blocking handle, so this test would prove nothing"
        )

        released = threading.Event()

        def _release() -> None:
            library.CloseHandle(blocker)
            released.set()

        timer = threading.Timer(0.25, _release)
        timer.start()
        try:
            with directory_lease(authority, publication=True) as leased:
                assert leased.native_handle is not None
        finally:
            timer.cancel()
            if not released.is_set():
                library.CloseHandle(blocker)

        assert released.is_set(), (
            "the lease returned before the blocking handle was released, so the "
            "collision never happened and the retry was not exercised"
        )

    def test_a_sharing_violation_is_reported_as_one(tmp_path: Path) -> None:
        """A Windows error code must not be read as a POSIX errno.

        ERROR_SHARING_VIOLATION is 32, and so is EPIPE. Passing the Windows code
        positionally makes Python pick the class from the errno table, so the one
        failure this module retries on arrived as ``BrokenPipeError`` carrying the
        text "another process" and no ``winerror`` - unclassifiable by any caller,
        and a diagnosis that reads "broken pipe" for a file someone else is
        holding. The assertion against the positional form is what keeps this
        honest: it fails if the two shapes ever stop disagreeing.
        """
        error = _windows_error(_ERROR_SHARING_VIOLATION, tmp_path / "held")

        assert isinstance(error, PermissionError)
        assert not isinstance(error, BrokenPipeError)
        assert error.winerror == _ERROR_SHARING_VIOLATION
        assert error.errno == errno.EACCES
        assert error.filename == str(tmp_path / "held")
        assert "another process" in str(error)

        positional = OSError(
            _ERROR_SHARING_VIOLATION,
            ctypes.FormatError(_ERROR_SHARING_VIOLATION),
            str(tmp_path / "held"),
        )
        assert isinstance(positional, BrokenPipeError)
        assert positional.winerror is None
