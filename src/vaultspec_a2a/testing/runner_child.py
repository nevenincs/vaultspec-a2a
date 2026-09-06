"""Contained pytest entrypoint that binds completion to its own process."""

from __future__ import annotations

import os
import sys

import pytest

from .runner import COMPLETION_OWNER_PID_ENV


def main() -> int:
    os.environ[COMPLETION_OWNER_PID_ENV] = str(os.getpid())
    return pytest.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
