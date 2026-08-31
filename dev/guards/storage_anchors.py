"""Gate: production code must not anchor storage to the repository layout.

A shipped package does not know where it lives. When production code derives a
mutable path from its own source location, from the repository root, or from
whatever directory the process happened to start in, the result is correct only
in a source checkout: an installed wheel resolves the same expression into the
Python library directory, and a service resolves it against an inherited
working directory. Both are silent - nothing fails, the data simply lands
somewhere nobody looks.

Three anchors are refused:

- **Escaping ``__file__`` walks.** A module may walk up to its OWN package root
  to reach bundled package data (``Path(__file__).parent / "presets"``). Walking
  past the package root reaches the source tree, which does not exist once the
  package is installed.
- **``Path.cwd()`` / ``os.getcwd()``.** The working directory is inherited from
  whoever launched the process. Two callers of the same code then disagree about
  where the data is.
- **``settings.project_root`` as an anchor.** The field remains legitimate for
  resolving provider assets; it is not a storage root, and reading it outside
  the module that defines it is how it became one.

Resolving package data through ``importlib.resources`` is the supported form and
is never reported: it asks the installed distribution where its own files are
rather than inferring it from a path.

Run through the harness::

    just dev lint anchors

A genuinely correct use - a development-only entry point, an anchor that is
itself the configured override seam - is exempted with a trailing
``# storage-anchor-ok`` comment on the offending line.

``DEFERRED`` lists modules whose violations are known, owned, and not yet
closed. It is a debt list, not an exemption list: the gate reports its contents
on every run so the remaining work stays visible, and an entry is deleted as
its module is fixed rather than left to accumulate.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

#: The package whose production modules are gated.
PACKAGE = "vaultspec_a2a"

#: Source root scanned by the gate.
ROOT = Path("src") / PACKAGE

#: Trailing comment that exempts a single line.
ALLOW = "storage-anchor-ok"

#: Directory names whose contents are test code rather than shipped production
#: code. Tests legitimately construct paths against the checkout they run in.
TEST_DIRS = frozenset(
    {"tests", "desktop_tests", "service_tests", "acceptance", "testing"}
)

#: Modules with known, owned violations that are not yet closed, each mapped to
#: the reason it is still open. Delete an entry when its module is fixed; do not
#: add one without an owner for the work.
DEFERRED: dict[str, str] = {
    "lifecycle/manager.py": (
        "the managed-process registry seats a serve command at the repository "
        "root; the registry is development harness shipped inside the package "
        "and its home is unresolved"
    ),
    "lifecycle/procs_config.py": (
        "the managed-process table is read from the repository root; same "
        "unresolved home as the registry above"
    ),
}


def _is_test_module(relative: Path) -> bool:
    """Return whether a package-relative module is test rather than product code."""
    return any(part in TEST_DIRS for part in relative.parts)


def _parents_to_package_root(relative: Path) -> int:
    """Return the number of ``.parent`` steps that reach the package root.

    ``control/config.py`` sits two parts below the package root, so two steps
    reach ``vaultspec_a2a`` itself and anything beyond that leaves the installed
    package behind.
    """
    return len(relative.parts)


def _walk_violations(tree: ast.Module, relative: Path) -> list[tuple[int, str]]:
    """Return every ``__file__`` parent walk that escapes the package root."""
    budget = _parents_to_package_root(relative)
    deepest: dict[int, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != "parent":
            continue
        text = ast.unparse(node)
        if "__file__" not in text:
            continue
        steps = text.count(".parent")
        # Keep only the longest chain reported on a line: the inner nodes of
        # ``a.parent.parent`` are themselves ``.parent`` attributes and would
        # otherwise each report a shorter, duplicate walk.
        if steps > deepest.get(node.lineno, 0):
            deepest[node.lineno] = steps
    return [
        (
            lineno,
            f"__file__ walk of {steps} parents escapes the package root "
            f"(at most {budget} stays inside the installed package)",
        )
        for lineno, steps in sorted(deepest.items())
        if steps > budget
    ]


def _cwd_violations(tree: ast.Module) -> list[tuple[int, str]]:
    """Return every working-directory read."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr == "cwd" and isinstance(func.value, ast.Name):
            if func.value.id == "Path":
                found.append(
                    (node.lineno, "Path.cwd() anchors to the launch directory")
                )
        elif func.attr == "getcwd":
            found.append((node.lineno, "os.getcwd() anchors to the launch directory"))
    return sorted(found)


def _project_root_violations(tree: ast.Module, relative: Path) -> list[tuple[int, str]]:
    """Return every read of ``project_root`` outside the module that defines it."""
    if relative.as_posix() == "control/config.py":
        return []
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "project_root":
            found.append((node.lineno, "settings.project_root used as a path anchor"))
    return sorted(found)


def main() -> int:
    """Scan production modules and report every repository-anchored path.

    Returns:
        0 when no undeferred violation remains, 1 when any does, and 2 when the
        source root is missing (which means the gate was run from the wrong
        directory and must not report a false pass).
    """
    if not ROOT.is_dir():
        print(
            f"{ROOT} not found - run this from the repository root.",
            file=sys.stderr,
        )
        return 2

    violations: list[str] = []
    deferred_hits: dict[str, int] = {}

    for path in sorted(ROOT.rglob("*.py")):
        relative = path.relative_to(ROOT)
        if _is_test_module(relative):
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            print(f"{path}: could not parse: {exc}", file=sys.stderr)
            return 2

        found = (
            _walk_violations(tree, relative)
            + _cwd_violations(tree)
            + _project_root_violations(tree, relative)
        )
        key = relative.as_posix()
        for lineno, reason in sorted(found):
            source = lines[lineno - 1] if lineno <= len(lines) else ""
            if ALLOW in source:
                continue
            if key in DEFERRED:
                deferred_hits[key] = deferred_hits.get(key, 0) + 1
                continue
            violations.append(f"{path}:{lineno}: {reason}")

    if deferred_hits:
        total = sum(deferred_hits.values())
        print(
            f"{total} known violation(s) remain in {len(deferred_hits)} deferred "
            f"module(s) - open debt, not accepted design:",
            file=sys.stderr,
        )
        for key in sorted(deferred_hits):
            print(
                f"  {key}: {deferred_hits[key]} - {DEFERRED[key]}",
                file=sys.stderr,
            )

    stale = sorted(set(DEFERRED) - set(deferred_hits))
    if stale:
        print(
            "deferred entries no longer match any violation and must be deleted:",
            file=sys.stderr,
        )
        for key in stale:
            print(f"  {key}", file=sys.stderr)
        return 1

    if violations:
        print(
            f"{len(violations)} repository-anchored path(s) in production code. "
            f"Resolve package data through importlib.resources, take the "
            f"directory from configuration, or annotate the line with "
            f"# {ALLOW}:",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
