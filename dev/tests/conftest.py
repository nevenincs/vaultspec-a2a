"""Make the harness importable to its own tests.

``pytest dev`` collects these modules from a directory that carries no
``__init__.py``, so pytest's ``prepend`` import mode puts ``dev/tests`` on
``sys.path`` rather than the repository root, and ``import dev.repo`` would
fail. Inserting the root here keeps ``just dev test harness`` self-contained
instead of depending on where the caller happened to start it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
