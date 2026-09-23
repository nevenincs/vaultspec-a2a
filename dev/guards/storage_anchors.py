"""Gate: production code keeps every path and setting inside its one authority.

a2a writes only beneath the state home, which lives in the project it serves,
and reads its configuration only through the settings module. Each rule below
refuses one way code has escaped that - silently, because nothing fails when
data lands somewhere nobody looks:

- **Escaping ``__file__`` walks.** A module may walk up to its OWN package root
  to reach bundled package data (``Path(__file__).parent / "presets"``). Walking
  past the package root reaches the source tree, which does not exist once the
  package is installed.
- **``Path.cwd()`` / ``os.getcwd()``.** The working directory is inherited from
  whoever launched the process; the project root is the one place it is read.
- **``Path.home()`` / ``expanduser()``.** a2a never writes into the user
  profile. Reading another tool's own home (a CLI's login directory) is the
  legitimate use, and is annotated as such where it happens.
- **``tempfile`` without ``dir=``.** The system temporary directory is outside
  every state a2a accounts for; a temporary file or directory is placed under
  the state home's temporary root instead.
- **Raw environment reads.** ``os.environ.get``, ``os.getenv`` and
  ``os.environ[...]`` outside the settings module bypass the one declaration of
  a setting, its prefix, its dotenv and its documentation.
- **Spelled-out setting names.** A ``VAULTSPEC_*`` name written as a literal
  outside the settings modules is a second declaration of a setting; a child
  environment takes the name from the schema (``setting_env``) instead. The
  names sibling vaultspec tools own are theirs to spell.
- **``install_root`` as an anchor.** The field resolves this service's shipped
  assets; read anywhere but the asset resolver, it becomes a storage root.

Resolving package data through ``importlib.resources`` is the supported form and
is never reported.

Test modules and the repository's own tooling under ``dev/`` are held to the
``tempfile`` rule alone: they may read the checkout and the environment, but
their scratch space belongs to the worktree (the test session's seat, or an
ignored ``.tmp-*`` directory), never to a system directory a sandboxed host
cannot write.

Run through the harness::

    just check-anchors

A genuinely correct use is exempted with a trailing ``# storage-anchor-ok``
comment on the offending line, next to a comment saying why.

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

#: Repository tooling, held to the ``tempfile`` rule only.
TOOLING_ROOT = Path("dev")

#: Trailing comment that exempts a single line.
ALLOW = "storage-anchor-ok"

#: The settings module: the one place the environment is read.
SETTINGS_MODULES = frozenset({"control/settings_base.py"})

#: The modules that declare settings, and so spell their names.
NAME_DECLARING_MODULES = frozenset(
    {
        "control/settings_base.py",
        "control/infra_config.py",
        "control/config.py",
        "domain_config.py",
    }
)

#: Names owned by sibling vaultspec tools, written for their servers only.
SIBLING_NAMES = frozenset({"VAULTSPEC_RAG_ROOT", "VAULTSPEC_TARGET_DIR"})

#: The modules allowed to read ``install_root``: its declaration, and the
#: resolver of the assets it exists to locate.
INSTALL_ROOT_READERS = frozenset(
    {"control/infra_config.py", "control/config.py", "providers/_factory_commands.py"}
)

#: ``tempfile`` entry points that create or name a file or directory.
_TEMPFILE_CALLS = frozenset(
    {
        "mkdtemp",
        "mkstemp",
        "gettempdir",
        "TemporaryDirectory",
        "TemporaryFile",
        "NamedTemporaryFile",
        "SpooledTemporaryFile",
    }
)

#: Directory names whose contents are test code rather than shipped production
#: code. Tests legitimately construct paths against the checkout they run in.
TEST_DIRS = frozenset(
    {"tests", "desktop_tests", "service_tests", "acceptance", "testing"}
)

#: Modules with known, owned violations that are not yet closed, each mapped to
#: the reason it is still open. Delete an entry when its module is fixed; do not
#: add one without an owner for the work.
DEFERRED: dict[str, str] = {}


def _is_test_module(relative: Path) -> bool:
    """Return whether a package-relative module is test rather than product code."""
    return relative.name == "conftest.py" or any(
        part in TEST_DIRS for part in relative.parts
    )


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


def _names_path(node: ast.expr) -> bool:
    """Whether ``node`` is ``Path`` itself or any attribute chain ending in it."""
    if isinstance(node, ast.Name):
        return node.id == "Path"
    return isinstance(node, ast.Attribute) and node.attr == "Path"


def _cwd_violations(tree: ast.Module) -> list[tuple[int, str]]:
    """Return every working-directory read."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr == "cwd" and _names_path(func.value):
            found.append((node.lineno, "Path.cwd() anchors to the launch directory"))
        elif func.attr == "getcwd":
            found.append((node.lineno, "os.getcwd() anchors to the launch directory"))
    return sorted(found)


def _home_violations(tree: ast.Module) -> list[tuple[int, str]]:
    """Return every user-profile anchor."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        func = node.func
        if func.attr == "home" and _names_path(func.value):
            found.append((node.lineno, "Path.home() anchors to the user profile"))
        elif func.attr == "expanduser":
            found.append((node.lineno, "expanduser() anchors to the user profile"))
    return sorted(found)


def _tempfile_aliases(tree: ast.Module) -> dict[str, str]:
    """Map every local name bound by ``from tempfile import ...`` to its entry."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "tempfile":
            for alias in node.names:
                if alias.name in _TEMPFILE_CALLS:
                    aliases[alias.asname or alias.name] = alias.name
    return aliases


def _places_under_a_directory(node: ast.Call) -> bool:
    """Whether the call names a directory - and not ``None``, the system default."""
    for keyword in node.keywords:
        if keyword.arg == "dir":
            value = keyword.value
            return not (isinstance(value, ast.Constant) and value.value is None)
    return False


def _tempfile_violations(tree: ast.Module) -> list[tuple[int, str]]:
    """Return every ``tempfile`` call that lands in the system temp directory."""
    aliases = _tempfile_aliases(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "tempfile"
            and func.attr in _TEMPFILE_CALLS
        ):
            entry = func.attr
        elif isinstance(func, ast.Name) and func.id in aliases:
            entry = aliases[func.id]
        else:
            continue
        if entry != "gettempdir" and _places_under_a_directory(node):
            continue
        found.append(
            (node.lineno, f"tempfile.{entry}() lands in the system temp directory")
        )
    return sorted(found)


def _is_os_environ(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _env_read_violations(tree: ast.Module, relative: Path) -> list[tuple[int, str]]:
    """Return every named environment read outside the settings module."""
    if relative.as_posix() in SETTINGS_MODULES:
        return []
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            if func.attr == "get" and _is_os_environ(func.value):
                found.append((node.lineno, "os.environ.get() bypasses the settings"))
            elif (
                func.attr == "getenv"
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            ):
                found.append((node.lineno, "os.getenv() bypasses the settings"))
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Load)
            and _is_os_environ(node.value)
        ):
            found.append((node.lineno, "os.environ[...] bypasses the settings"))
    return sorted(found)


def _name_literal_violations(tree: ast.Module, relative: Path) -> list[tuple[int, str]]:
    """Return every setting name spelled out outside the declaring modules."""
    if relative.as_posix() in NAME_DECLARING_MODULES:
        return []
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        value = node.value
        if (
            value.startswith("VAULTSPEC_")
            # A prefix ("VAULTSPEC_") names a family, not a setting.
            and not value.endswith("_")
            and value.replace("_", "").isalnum()
            and value.isupper()
            and value not in SIBLING_NAMES
        ):
            found.append(
                (node.lineno, f"{value} spelled out; take it from setting_env()")
            )
    return sorted(found)


def _install_root_violations(tree: ast.Module, relative: Path) -> list[tuple[int, str]]:
    """Return every read of ``install_root`` outside the asset resolver."""
    if relative.as_posix() in INSTALL_ROOT_READERS:
        return []
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "install_root":
            found.append((node.lineno, "settings.install_root used as a path anchor"))
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

    scanned: list[tuple[Path, Path | None]] = [
        (path, path.relative_to(ROOT)) for path in sorted(ROOT.rglob("*.py"))
    ]
    scanned += [(path, None) for path in sorted(TOOLING_ROOT.rglob("*.py"))]
    for path, relative in scanned:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            print(f"{path}: could not parse: {exc}", file=sys.stderr)
            return 2

        if relative is None or _is_test_module(relative):
            found = _tempfile_violations(tree)
        else:
            found = (
                _walk_violations(tree, relative)
                + _cwd_violations(tree)
                + _home_violations(tree)
                + _tempfile_violations(tree)
                + _env_read_violations(tree, relative)
                + _install_root_violations(tree, relative)
                + _name_literal_violations(tree, relative)
            )
        key = (relative if relative is not None else path).as_posix()
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
            f"{len(violations)} escape(s) from the path and settings "
            f"authority. Resolve package data through "
            f"importlib.resources, take the location or value from settings, "
            f"or annotate a genuine exception with # {ALLOW}:",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
