"""A credential Codex refreshes inside a run home reaches the login it came from.

Real files and a real second process: the write-back is a filesystem contract
between concurrent runs, so nothing here stands in for the filesystem or for the
other run. The refresh itself is written the way Codex writes it - a replaced
``auth.json`` carrying a later ``last_refresh`` - because that is the only part of
the rotation this side ever observes.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ...utils.enums import CodexWebSearchMode
from .._codex_auth import (
    CODEX_AUTH_FILENAME,
    codex_credential_store_mode,
    forget_run_credential,
    seed_run_credential,
    write_back_refreshed_credential,
)
from .._codex_config_home import build_codex_config_home, cleanup_codex_config_home

if TYPE_CHECKING:
    import pytest

    from .._json_contract import JsonObject

_NO_SPECS: list[JsonObject] = []
# The checkout's importable source root, handed to the child so it imports the
# same production module this test drives.
_SOURCE_ROOT = Path(__file__).resolve().parents[3]
_BASE = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)


def _credential(token: str, *, refreshed: datetime) -> bytes:
    """One Codex credential document, in the shape the CLI writes it."""
    return json.dumps(
        {
            "OPENAI_API_KEY": None,
            "tokens": {"refresh_token": token, "account_id": "acct-1"},
            "last_refresh": refreshed.isoformat().replace("+00:00", "Z"),
        }
    ).encode("utf-8")


def _base_home(tmp_path: Path, *, token: str = "seeded", config: str = "") -> Path:
    """Create a Codex login home holding one credential."""
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / CODEX_AUTH_FILENAME).write_bytes(_credential(token, refreshed=_BASE))
    if config:
        (home / "config.toml").write_text(config, encoding="utf-8")
    return home


def _run_home(base_home: Path) -> Path:
    """Build the per-run home through the production seam."""
    return build_codex_config_home(
        _NO_SPECS, base_home, web_search=CodexWebSearchMode.DISABLED
    )


def _refresh_in(home: Path, *, token: str, after_seconds: int) -> bytes:
    """Write the credential Codex would leave behind after a rotation."""
    payload = _credential(token, refreshed=_BASE + timedelta(seconds=after_seconds))
    (home / CODEX_AUTH_FILENAME).write_bytes(payload)
    return payload


def test_a_refreshed_credential_is_written_back_on_cleanup(tmp_path: Path) -> None:
    """The rotation survives the removal of the home it happened in."""
    base_home = _base_home(tmp_path)
    run_home = _run_home(base_home)
    refreshed = _refresh_in(run_home, token="rotated", after_seconds=60)

    cleanup_codex_config_home(run_home)

    assert (base_home / CODEX_AUTH_FILENAME).read_bytes() == refreshed
    assert not run_home.exists()


def test_child_seed_metadata_cannot_redirect_refresh(tmp_path: Path) -> None:
    base_home = _base_home(tmp_path)
    run_home = _run_home(base_home)
    victim = tmp_path / "worker-state.json"
    victim.write_bytes(b"private worker state")
    (run_home / ".vaultspec-codex-auth-seed.json").write_text(
        json.dumps({"source": str(victim), "digest": "forged", "last_refresh": None}),
        encoding="utf-8",
    )
    refreshed = _refresh_in(run_home, token="rotated", after_seconds=60)

    cleanup_codex_config_home(run_home)

    assert victim.read_bytes() == b"private worker state"
    assert (base_home / CODEX_AUTH_FILENAME).read_bytes() == refreshed


def test_unseeded_home_cannot_claim_a_refresh_destination(tmp_path: Path) -> None:
    victim = tmp_path / "worker-state.json"
    victim.write_bytes(b"private worker state")
    run_home = tmp_path / "unseeded"
    run_home.mkdir()
    _refresh_in(run_home, token="forged", after_seconds=60)
    (run_home / ".vaultspec-codex-auth-seed.json").write_text(
        json.dumps({"source": str(victim), "digest": "forged", "last_refresh": None}),
        encoding="utf-8",
    )

    assert not write_back_refreshed_credential(run_home)
    assert victim.read_bytes() == b"private worker state"


def test_hardlinked_returned_credential_is_not_published(tmp_path: Path) -> None:
    base_home = _base_home(tmp_path)
    source = base_home / CODEX_AUTH_FILENAME
    seeded = source.read_bytes()
    run_home = _run_home(base_home)
    shared = run_home / "shared-auth.json"
    shared.write_bytes(_credential("foreign", refreshed=_BASE + timedelta(seconds=60)))
    (run_home / CODEX_AUTH_FILENAME).unlink()
    os.link(shared, run_home / CODEX_AUTH_FILENAME)
    try:
        assert not write_back_refreshed_credential(run_home)
        assert source.read_bytes() == seeded
    finally:
        cleanup_codex_config_home(run_home)


def test_non_json_returned_credential_is_not_published(tmp_path: Path) -> None:
    base_home = _base_home(tmp_path)
    source = base_home / CODEX_AUTH_FILENAME
    seeded = source.read_bytes()
    run_home = _run_home(base_home)
    (run_home / CODEX_AUTH_FILENAME).write_text("arbitrary text", encoding="utf-8")
    try:
        assert not write_back_refreshed_credential(run_home)
        assert source.read_bytes() == seeded
    finally:
        cleanup_codex_config_home(run_home)


def test_replaced_run_directory_cannot_return_credentials(tmp_path: Path) -> None:
    base_home = _base_home(tmp_path)
    source = base_home / CODEX_AUTH_FILENAME
    seeded = source.read_bytes()
    run_home = _run_home(base_home)
    with tempfile.TemporaryDirectory(dir=run_home.parent) as moved_root:
        moved = Path(moved_root) / "original"
        run_home.rename(moved)
        run_home.mkdir()
        _refresh_in(run_home, token="substituted", after_seconds=60)
        try:
            assert not write_back_refreshed_credential(run_home)
            assert source.read_bytes() == seeded
        finally:
            cleanup_codex_config_home(run_home)


def test_oversized_returned_credential_is_not_published(tmp_path: Path) -> None:
    base_home = _base_home(tmp_path)
    source = base_home / CODEX_AUTH_FILENAME
    seeded = source.read_bytes()
    run_home = _run_home(base_home)
    (run_home / CODEX_AUTH_FILENAME).write_bytes(b" " * (1024 * 1024 + 1))
    try:
        assert not write_back_refreshed_credential(run_home)
        assert source.read_bytes() == seeded
    finally:
        cleanup_codex_config_home(run_home)


def test_refresh_accepts_a_home_beneath_a_directory_alias(tmp_path: Path) -> None:
    base_home = _base_home(tmp_path)
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    if os.name == "nt":
        completed = subprocess.run(
            [os.environ["COMSPEC"], "/d", "/c", "mklink", "/J", str(alias), str(real)],
            capture_output=True,
            text=True,
            check=True,
        )
        assert alias.is_junction(), completed.stdout
    else:
        alias.symlink_to(real, target_is_directory=True)
    run_home = alias / "run"
    run_home.mkdir()
    try:
        assert seed_run_credential(base_home, run_home) is not None
        refreshed = _refresh_in(run_home, token="rotated", after_seconds=60)
        assert write_back_refreshed_credential(run_home)
        assert (base_home / CODEX_AUTH_FILENAME).read_bytes() == refreshed
    finally:
        forget_run_credential(run_home)
        if os.name == "nt":
            alias.rmdir()
        else:
            alias.unlink()


def test_finished_retained_home_has_no_refresh_authority(tmp_path: Path) -> None:
    from ...testing import settings_override

    base_home = _base_home(tmp_path)
    run_home = _run_home(base_home)
    source = base_home / CODEX_AUTH_FILENAME
    seeded = source.read_bytes()
    try:
        with settings_override(codex_config_home_retain=True):
            cleanup_codex_config_home(run_home)
        _refresh_in(run_home, token="after-cleanup", after_seconds=60)
        assert not write_back_refreshed_credential(run_home)
        assert source.read_bytes() == seeded
    finally:
        cleanup_codex_config_home(run_home)


def test_deeply_nested_returned_json_is_not_published(tmp_path: Path) -> None:
    base_home = _base_home(tmp_path)
    source = base_home / CODEX_AUTH_FILENAME
    seeded = source.read_bytes()
    run_home = _run_home(base_home)
    (run_home / CODEX_AUTH_FILENAME).write_text("[" * 10000 + "]" * 10000)
    try:
        assert not write_back_refreshed_credential(run_home)
        assert source.read_bytes() == seeded
    finally:
        cleanup_codex_config_home(run_home)


def test_bytes_that_are_not_a_login_are_never_written_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A run home left holding undecodable bytes does not overwrite the login."""
    base_home = _base_home(tmp_path)
    seeded = (base_home / CODEX_AUTH_FILENAME).read_bytes()
    run_home = _run_home(base_home)
    (run_home / CODEX_AUTH_FILENAME).write_bytes(b"\xff\xfe not a login")

    with caplog.at_level(logging.ERROR):
        cleanup_codex_config_home(run_home)

    assert (base_home / CODEX_AUTH_FILENAME).read_bytes() == seeded
    assert not run_home.exists()
    assert "not UTF-8 text" in caplog.text


def test_an_untouched_credential_is_left_exactly_as_it_was(tmp_path: Path) -> None:
    """A run that never refreshed writes nothing, not even the same bytes back."""
    base_home = _base_home(tmp_path)
    source = base_home / CODEX_AUTH_FILENAME
    before = source.stat()
    run_home = _run_home(base_home)

    assert write_back_refreshed_credential(run_home) is False

    after = source.stat()
    # A replaced file is a new inode and a new mtime; neither moved.
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    cleanup_codex_config_home(run_home)


def test_a_login_another_run_refreshed_later_is_not_overwritten(
    tmp_path: Path,
) -> None:
    """The newest rotation is the only one the provider still honours."""
    base_home = _base_home(tmp_path)
    run_home = _run_home(base_home)
    _refresh_in(run_home, token="this-run", after_seconds=30)
    newer = _refresh_in(base_home, token="other-run", after_seconds=90)

    assert write_back_refreshed_credential(run_home) is False
    assert (base_home / CODEX_AUTH_FILENAME).read_bytes() == newer
    cleanup_codex_config_home(run_home)


def test_a_login_this_run_refreshed_later_wins_over_an_older_source(
    tmp_path: Path,
) -> None:
    """Being overtaken is decided by the stamp, not by who wrote last."""
    base_home = _base_home(tmp_path)
    run_home = _run_home(base_home)
    mine = _refresh_in(run_home, token="this-run", after_seconds=120)
    _refresh_in(base_home, token="other-run", after_seconds=45)

    assert write_back_refreshed_credential(run_home) is True
    assert (base_home / CODEX_AUTH_FILENAME).read_bytes() == mine
    cleanup_codex_config_home(run_home)


def test_a_login_kept_outside_the_home_is_reported_with_its_store_mode(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No credential file means "kept elsewhere", which the run says out loud.

    Silence here is the defect: the run starts unauthenticated and looks exactly
    like a lane the operator never logged into.
    """
    base_home = tmp_path / "codex-home"
    base_home.mkdir()
    (base_home / "config.toml").write_text(
        'cli_auth_credentials_store = "keyring"\n', encoding="utf-8"
    )
    run_home = tmp_path / "run-home"
    run_home.mkdir()

    assert codex_credential_store_mode(base_home) == "keyring"
    with caplog.at_level(logging.WARNING, logger="vaultspec_a2a.providers"):
        assert seed_run_credential(base_home, run_home) is None

    assert any("keyring" in record.getMessage() for record in caplog.records), (
        caplog.messages
    )
    assert not (run_home / CODEX_AUTH_FILENAME).exists()


def test_a_write_back_serialises_against_another_process(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Two runs sharing one login take turns through a real inter-process lock.

    The other run is a real child process holding the production lock while this
    one asks for it, so what is proven is that the lock crosses processes rather
    than that two calls in one process take turns. The short-timeout call proves
    the wait is real - it gives up loudly while the child still holds it - and the
    default-timeout call then proves the write-back completes once it is released.
    """
    base_home = _base_home(tmp_path)
    run_home = _run_home(base_home)
    refreshed = _refresh_in(run_home, token="rotated", after_seconds=60)
    source = base_home / CODEX_AUTH_FILENAME
    ready = tmp_path / "holding"
    holder = f"""
import pathlib, time
from vaultspec_a2a.providers._codex_auth import _credential_lock
with _credential_lock(pathlib.Path({str(source)!r})):
    pathlib.Path({str(ready)!r}).write_text("held")
    time.sleep(3)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", holder],
        env={**os.environ, "PYTHONPATH": str(_SOURCE_ROOT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20.0
        while not ready.exists():
            assert child.poll() is None, child.communicate()
            assert time.monotonic() < deadline, "the holder never took the lock"
            time.sleep(0.05)

        with caplog.at_level(logging.ERROR, logger="vaultspec_a2a.providers"):
            assert (
                write_back_refreshed_credential(run_home, lock_timeout_seconds=0.2)
                is False
            )
        # Refused, not written: the holder still owns the credential, and the
        # refusal is loud rather than silent - the operator's login may now hold a
        # token this run watched being retired.
        assert source.read_bytes() != refreshed
        assert any(
            "could not be written back" in record.getMessage()
            for record in caplog.records
        ), caplog.messages
    finally:
        child.terminate()
        child.wait(timeout=20)

    assert write_back_refreshed_credential(run_home) is True
    assert source.read_bytes() == refreshed
    cleanup_codex_config_home(run_home)
