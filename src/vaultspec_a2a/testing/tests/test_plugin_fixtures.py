"""Acquisition fixtures exercised in-suite, against the real allocator."""

from __future__ import annotations

import socket

from ...lifecycle import load_procs_config


def test_leased_port_comes_from_the_scratch_band_and_binds(leased_port: int) -> None:
    """The port is a real scratch-band reservation, bindable right now.

    Allocation went through the registry's ``reserve_port`` - the same
    race-free ``O_EXCL`` claim the lifecycle verbs use - so a concurrent
    session can never have been handed the same port.
    """
    band = load_procs_config().role("scratch").band
    assert leased_port in band
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", leased_port))
