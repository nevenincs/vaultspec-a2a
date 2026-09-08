"""The repository's development tooling harness.

Nothing in this package ships. It exists so that every development action the
repository performs on itself - static analysis, audits, code-health
measurement, environment diagnosis - has ONE home, ONE declarative definition,
and ONE platform-agnostic implementation.

The layering is deliberate:

``runner``
    Process-execution primitives. Standard library only.
``toolchain``
    The declarative registry of verbs and targets. Standard library only, and
    the single source of truth for what the harness can do.
``__main__``
    Dispatch. Standard library only.

Those three modules are the stdlib-only dispatch core. The sub-packages beside
them - :mod:`dev.guards`, :mod:`dev.health` - are the INSTRUMENTS the verbs
invoke when a measurement is too large to express as a command line. They are
free to depend on whatever they measure with, which is why they sit one level
below the dispatch core rather than inside it.

The justfile exposes each verb and holds no logic of its own: every recipe body
is a single ``python -m dev <verb> <target>`` invocation with no shell
branching, no pipes, and no PowerShell-versus-sh dialect to maintain.
"""

from __future__ import annotations

import os
import sys

# Windows starts a Python process with its streams bound to the ANSI codepage
# (cp1252 on a stock installation), so ONE box-drawing character or accented
# identifier - in a tool's output, or in the command line this harness echoes
# before running it - raises UnicodeEncodeError and takes the recipe down with
# it. The failure belongs to Python, not the shell: it reproduces identically
# under `cmd` and under `pwsh`, so no choice of `set windows-shell` avoids it
# and the fix has to live here.
#
# Both halves are load bearing. Reconfiguring this process's own streams covers
# everything the harness itself prints; exporting PYTHONIOENCODING covers every
# Python child it spawns, which is most of the toolchain. An explicit value from
# the operator or a caller wins, so a deliberate override still works.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        _reconfigure(encoding="utf-8")

__all__ = ["__doc__"]
