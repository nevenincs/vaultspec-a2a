"""Contained pytest entrypoint that binds completion to its own process."""

from __future__ import annotations

import os
import sys

import pytest

from .runner import COMPLETION_OWNER_PID_ENV


def main() -> int:
    previous_environment = os.environ.get("VAULTSPEC_ENVIRONMENT")
    os.environ.setdefault("VAULTSPEC_ENVIRONMENT", "development")
    os.environ[COMPLETION_OWNER_PID_ENV] = str(os.getpid())
    try:
        return pytest.main(sys.argv[1:])
    finally:
        if previous_environment is None:
            os.environ.pop("VAULTSPEC_ENVIRONMENT", None)
        else:
            os.environ["VAULTSPEC_ENVIRONMENT"] = previous_environment


if __name__ == "__main__":
    raise SystemExit(main())
