"""Trusted native launcher; never parses the provider's protocol input."""

from __future__ import annotations

import os
import sys

from .native_isolation import (
    NativeLaunchAuthority,
    decode_launch_environment,
    exec_linux_isolated,
)


def main() -> None:
    if len(sys.argv) < 4:
        raise ValueError("native isolation requires authority, cwd and command")
    exec_linux_isolated(
        NativeLaunchAuthority.decode(sys.argv[1]),
        sys.argv[3:],
        cwd=sys.argv[2],
        environment=decode_launch_environment(os.environ),
    )


if __name__ == "__main__":
    main()
