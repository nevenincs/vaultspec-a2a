"""Real-process desktop gateway harness for cross-repository certification."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Final

from ..tests.gateway_boot import (
    armed_gateway_env,
    gateway_script,
    reap_gateway,
    seat_valid_database,
    seed_credentials,
    spawn_gateway,
    spawn_until_ready,
)

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Iterator
    from pathlib import Path

ATTACH_CREDENTIAL: Final = "attach-credential-cross-repo-1234567890abcdef"
_OWNERSHIP: Final = "ownership-capability-cross-repo-fedcba0987654321"

# The INFO variant, so a cross-repository consumer reading this log sees the
# gateway's own narration rather than uvicorn access lines alone.
_GATEWAY: Final = gateway_script(log_level="info")


@contextlib.contextmanager
def armed_gateway(tmp_path: Path, **extra_env: str) -> Iterator[tuple[str, str]]:
    """Boot a migrated production desktop gateway and its real lazy worker."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    seed_credentials(app_home, attach=ATTACH_CREDENTIAL, ownership=_OWNERSHIP)
    seat_valid_database(app_home)

    log_path = tmp_path / "gateway.log"
    log_handle = log_path.open("wb")

    def _spawn(gateway_port: int, worker_port: int) -> subprocess.Popen[bytes]:
        return spawn_gateway(
            script=_GATEWAY,
            gateway_port=gateway_port,
            env=armed_gateway_env(
                app_home,
                gateway_port=gateway_port,
                worker_port=worker_port,
                extra=extra_env,
            ),
            log_handle=log_handle,
            new_session=True,
        )

    process, _gateway_port, _worker_port, base = spawn_until_ready(
        _spawn, log_path=log_path
    )
    try:
        yield base, f"Bearer {ATTACH_CREDENTIAL}"
    finally:
        # The whole TREE, cross-platform, and only while the child is still
        # alive: the previous hand-rolled POSIX ``killpg`` / Windows branch here
        # was a third copy of logic the shared reaper already owns.
        reap_gateway(process)
        log_handle.close()
