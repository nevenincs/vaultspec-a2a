"""The one canonical way a test acquires a port to bind.

Tests never name a port; they take what they are given. Acquisition rides the
dev-process registry's existing race-free allocate-and-claim - an ``O_EXCL``
reservation marker in the machine-global procs home over the committed scratch
band - so two concurrent claimants (workers, sessions, agents) can never be
handed the same port, and the claim is held for the whole time the caller uses
it, not probed-and-released.

This is deliberately NOT the same thing as the ephemeral free-port probe some
negative tests use (asking the OS for a port that is currently unclaimed, to
assert that nothing listens there). That probe hands out no claim and must
never be used to obtain a port a test will bind; binding goes through here.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from ..lifecycle import (
    ProcsConfig,
    load_procs_config,
    release_reservation,
    reserve_port,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ["SCRATCH_ROLE", "reserved_port"]

SCRATCH_ROLE = "scratch"


@contextlib.contextmanager
def reserved_port(
    *, home: Path | None = None, config: ProcsConfig | None = None
) -> Iterator[int]:
    """Hold an exclusively-reserved scratch-band port while the caller uses it.

    The reservation marker stays held for the body's duration and is released
    on exit, so the port cannot be handed to any other registry-aware claimant
    while the test binds it. ``home``/``config`` injection exists for the
    framework's own isolation tests; ordinary callers take the machine-global
    default so exclusion spans every concurrent session on the host.
    """
    resolved = config if config is not None else load_procs_config()
    reservation = reserve_port(
        SCRATCH_ROLE, resolved.role(SCRATCH_ROLE), home=home, config=resolved
    )
    try:
        yield reservation.port
    finally:
        release_reservation(reservation)
