"""Real-process desktop gateway harness for cross-repository certification."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from ..testing import (
    DEFAULT_ATTACH_AUTHORIZATION,
    armed_gateway_env,
    booted_gateway,
    gateway_script,
    seat_app_home,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@contextlib.contextmanager
def armed_gateway(tmp_path: Path, **extra_env: str) -> Generator[tuple[str, str]]:
    """Boot a migrated production desktop gateway and its real lazy worker.

    The INFO script variant, so a cross-repository consumer reading the log sees
    the gateway's own narration rather than uvicorn access lines alone.
    """
    app_home = tmp_path / "app-home"
    seat_app_home(app_home)
    with booted_gateway(
        armed_gateway_env(app_home, extra=extra_env),
        log_path=tmp_path / "gateway.log",
        script=gateway_script(log_level="info"),
        detached=True,
    ) as gateway:
        yield gateway.base_url, DEFAULT_ATTACH_AUTHORIZATION
