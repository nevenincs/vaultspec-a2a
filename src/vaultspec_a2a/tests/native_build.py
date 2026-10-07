"""Build the genuine pinned isolation helper once per test process."""

from __future__ import annotations

import runpy
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ..testing import session_scratch_dir

if TYPE_CHECKING:
    from collections.abc import Callable


@cache
def linux_isolation_helper() -> Path:
    """Use the production build recipe in this test session's private scratch."""
    build = cast(
        "Callable[[Path], Path]",
        runpy.run_path(
            str(
                Path(__file__).resolve().parents[3] / "scripts/build_linux_isolation.py"
            )
        )["build_static_helper"],
    )
    return build(session_scratch_dir("native-helper-") / "sources")
