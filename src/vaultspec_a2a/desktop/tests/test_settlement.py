"""The terminal-settlement callback never raises and always answers quickly.

``emit_run_settlement`` is the one gateway-to-dashboard callback that may run on
the hot path of settling a run, so every non-delivery it can meet - a dashboard
nobody is listening on, a disabled or malformed endpoint, a missing attach
credential - must resolve to a typed, bounded result instead of an exception or
an unbounded wait. Each case below arms the real desktop profile over a real
credentials directory; only the one fact under test (the port, the URL, the
credential file) differs between them.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from ...desktop._platform_acl import harden_credential_path
from ...desktop.credentials import ATTACH_CREDENTIAL_NAME
from ...desktop.profile import derive_state_paths
from ...desktop.settlement import emit_run_settlement
from ...testing import armed_desktop_app_home, free_port
from ...thread.enums import ThreadStatus

if TYPE_CHECKING:
    from pathlib import Path


def _seat_credentials(app_home: Path, *, attach: str | None) -> None:
    """Create the credentials directory, writing the attach file only if given."""
    credentials_dir = derive_state_paths(app_home).credentials_dir
    credentials_dir.mkdir(parents=True, exist_ok=True)
    if attach is not None:
        path = credentials_dir / ATTACH_CREDENTIAL_NAME
        path.write_text(attach, encoding="utf-8")
        harden_credential_path(path)


@pytest.mark.asyncio
async def test_a_closed_loopback_port_exhausts_its_bounded_retries(
    tmp_path: Path,
) -> None:
    """Nobody answers: three attempts, a typed failure, never an exception."""
    app_home = tmp_path / "app"
    _seat_credentials(app_home, attach="attach-credential-closed-port-case")
    closed_port = free_port()

    with armed_desktop_app_home(
        app_home, desktop_settlement_url=f"http://127.0.0.1:{closed_port}/settle"
    ):
        started = time.monotonic()
        result = await emit_run_settlement(
            run_id="run-closed-port",
            lease_id="lease-closed-port",
            terminal_status=ThreadStatus.COMPLETED,
        )
        elapsed = time.monotonic() - started

    assert result.delivered is False
    assert result.skipped is False
    assert result.attempts == 3
    assert result.reason is not None
    # Bounded: the capped backoff between three attempts against a port that
    # refuses instantly must settle in a handful of seconds, not hang.
    assert elapsed < 15.0, elapsed


@pytest.mark.parametrize(
    "blank_or_unsupported_url", ["", "   ", "ftp://dashboard/settle"]
)
@pytest.mark.asyncio
async def test_a_blank_or_unsupported_url_skips_without_an_attempt(
    tmp_path: Path, blank_or_unsupported_url: str
) -> None:
    app_home = tmp_path / "app"
    _seat_credentials(app_home, attach="attach-credential-blank-url-case")

    with armed_desktop_app_home(
        app_home, desktop_settlement_url=blank_or_unsupported_url
    ):
        result = await emit_run_settlement(
            run_id="run-blank-url",
            lease_id="lease-blank-url",
            terminal_status=ThreadStatus.COMPLETED,
        )

    assert result.skipped is True
    assert result.delivered is False
    assert result.attempts == 0


@pytest.mark.asyncio
async def test_a_missing_attach_credential_file_skips_without_an_attempt(
    tmp_path: Path,
) -> None:
    app_home = tmp_path / "app"
    # A real credentials directory exists, but the attach file inside it does not.
    _seat_credentials(app_home, attach=None)

    with armed_desktop_app_home(
        app_home, desktop_settlement_url="http://127.0.0.1:1/settle"
    ):
        result = await emit_run_settlement(
            run_id="run-no-credential",
            lease_id="lease-no-credential",
            terminal_status=ThreadStatus.COMPLETED,
        )

    assert result.skipped is True
    assert result.delivered is False
    assert result.attempts == 0
