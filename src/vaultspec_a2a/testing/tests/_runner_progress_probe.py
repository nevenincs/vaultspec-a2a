"""Intentional pre-result delay for runner progress reporting."""

from __future__ import annotations

import time


def test_delays_before_session_result() -> None:
    time.sleep(0.35)
