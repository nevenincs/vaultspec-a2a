"""The canonical port acquisition helper, against the real allocator.

Reservations are real ``O_EXCL`` markers; ports are really bound; concurrent
claimants are nested real contexts over one shared home.
"""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

from ..ports import SCRATCH_ROLE, reserved_port

if TYPE_CHECKING:
    from pathlib import Path

from ...lifecycle import load_procs_config


def test_reserved_port_is_in_band_and_bindable() -> None:
    """Reserved in the REAL machine-global home, because the bind is real.

    An isolated home would make this test blind to concurrent sessions'
    reservations while still binding on the shared loopback - it could bind a
    port a peer has reserved but not yet bound. Binding through the real home
    is the same discipline the fixture's ordinary callers get.
    """
    band = load_procs_config().role(SCRATCH_ROLE).band
    with reserved_port() as port:
        assert port in band
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))


def test_concurrent_reservations_never_share_a_port(tmp_path: Path) -> None:
    """Held claims exclude each other for as long as they are held."""
    with (
        reserved_port(home=tmp_path) as first,
        reserved_port(home=tmp_path) as second,
        reserved_port(home=tmp_path) as third,
    ):
        assert len({first, second, third}) == 3


def test_release_returns_the_port_to_the_band(tmp_path: Path) -> None:
    with reserved_port(home=tmp_path) as first:
        pass
    with reserved_port(home=tmp_path) as second:
        # The freed first port is allocatable again (first-free-in-band).
        assert second == first
