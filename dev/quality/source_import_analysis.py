"""Shared static-analysis primitives for reading this repository's source tree.

Every instrument that reasons about the import graph needs the same handful of
answers - what a file's dotted module name is, what a relative import resolves
to, which nodes sit under ``if TYPE_CHECKING:`` - and each one that derived
them itself derived them slightly differently. A relative-import resolver that
is off by one package level does not fail loudly; it quietly reports a live
module as unreachable.

Nothing here imports the production package. The whole analysis is static:
files are parsed, never executed, so an instrument can measure a tree whose
dependencies are not installed and cannot be misled by an import side effect.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from dev.paths import PACKAGE, REPO_ROOT, SKIPPED_DIRS, SRC_ROOT, UTF_8, is_test_path

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: Names that, used as the test of an ``if``, guard a block out of runtime.
#: ``typing.TYPE_CHECKING`` is the canonical spelling; the bare name is what
#: appears after ``from typing import TYPE_CHECKING``.
TYPE_CHECKING_NAMES: Final[frozenset[str]] = frozenset({"TYPE_CHECKING"})


class UnreadableSourceError(RuntimeError):
    """A source file could not be read or parsed, so the analysis is incomplete.

    Raised rather than skipped on purpose: an instrument that silently drops
    the files it could not read reports a smaller finding set than the tree
    warrants, and reads as an improvement.
    """


@dataclass(frozen=True, slots=True)
class SourceModule:
    """One parsed module in the tree under analysis.

    Args:
        name: The dotted module name.
        path: The file's absolute path.
        tree: The parsed module.
        is_test: Whether the module is test code.
    """

    name: str
    path: Path
    tree: ast.Module
    is_test: bool

    @property
    def package(self) -> str:
        """The dotted name of the package this module lives in."""
        return self.name.rpartition(".")[0]

    @property
    def is_package_init(self) -> bool:
        """Whether this module is a package's ``__init__``."""
        return self.path.name == "__init__.py"


def iter_python_files(root: Path) -> Iterator[Path]:
    """Yield every Python file beneath ``root``, in stable order.

    Args:
        root: The directory to walk.

    Yields:
        Each ``.py`` file, sorted, with cache and vendored directories skipped.
    """
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIPPED_DIRS for part in path.parts):
            continue
        yield path


def module_name_for(path: Path, src_root: Path = SRC_ROOT) -> str:
    """Return the dotted module name a source file is imported under.

    Args:
        path: The file's path.
        src_root: The import root the name is relative to.

    Returns:
        The dotted name. A package ``__init__.py`` takes its package's name,
        which is what an importer actually writes.
    """
    relative = path.resolve().relative_to(src_root.resolve())
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(parts)


def parse_module(path: Path) -> ast.Module:
    """Parse one source file.

    Args:
        path: The file to parse.

    Returns:
        The parsed module.

    Raises:
        UnreadableSourceError: When the file cannot be read or does not parse.
    """
    try:
        return ast.parse(path.read_text(encoding=UTF_8), filename=str(path))
    except (OSError, SyntaxError, ValueError) as exc:
        msg = f"{path} could not be parsed: {exc}"
        raise UnreadableSourceError(msg) from exc


def load_modules(root: Path, *, src_root: Path = SRC_ROOT) -> dict[str, SourceModule]:
    """Parse every module beneath ``root``, keyed by dotted name.

    Args:
        root: The directory to load.
        src_root: The import root names are resolved against.

    Returns:
        Every module, keyed by dotted name.

    Raises:
        UnreadableSourceError: When any file cannot be parsed.
    """
    modules: dict[str, SourceModule] = {}
    for path in iter_python_files(root):
        name = module_name_for(path, src_root)
        modules[name] = SourceModule(
            name=name,
            path=path,
            tree=parse_module(path),
            is_test=is_test_path(path),
        )
    return modules


def resolve_relative_import(
    node: ast.ImportFrom, importer: str, *, is_package: bool
) -> str:
    """Resolve a relative ``from`` import to its absolute dotted target.

    Args:
        node: The import statement.
        importer: The dotted name of the importing module.
        is_package: Whether the importer is a package ``__init__``.

    Returns:
        The absolute dotted module the import names, or the empty string when
        the level walks above the tree root.

    A level-1 import inside ``a.b.c`` resolves against ``a.b``, but inside the
    package ``a.b`` (its ``__init__``) it resolves against ``a.b`` itself -
    the ``__init__`` IS the package, so it has one fewer level to strip. Off by
    one here turns a live module into a phantom one.
    """
    base = importer.split(".") if is_package else importer.split(".")[:-1]
    strip = node.level - 1
    if strip > len(base):
        return ""
    anchor = base[: len(base) - strip] if strip else base
    tail = node.module.split(".") if node.module else []
    return ".".join([*anchor, *tail])


def type_checking_guarded_nodes(tree: ast.Module) -> frozenset[int]:
    """Return the ids of every node that only executes under type checking.

    Args:
        tree: The parsed module.

    Returns:
        The ``id()`` of every node inside an ``if TYPE_CHECKING:`` body. An
        import reached only through one of these never runs, so a module
        reachable only that way is not reachable at runtime.
    """
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not _is_type_checking_test(node.test):
            continue
        for statement in node.body:
            guarded.update(id(child) for child in ast.walk(statement))
    return frozenset(guarded)


def _is_type_checking_test(test: ast.expr) -> bool:
    """Return whether an ``if`` test is the TYPE_CHECKING guard."""
    if isinstance(test, ast.Name):
        return test.id in TYPE_CHECKING_NAMES
    if isinstance(test, ast.Attribute):
        return test.attr in TYPE_CHECKING_NAMES
    return False


def imported_modules(
    module: SourceModule,
    *,
    guarded: frozenset[int] | None = None,
) -> tuple[frozenset[str], frozenset[str]]:
    """Return the modules a module imports, split by whether they run.

    Args:
        module: The module to read.
        guarded: Pre-computed TYPE_CHECKING node ids, or ``None`` to compute.

    Returns:
        ``(runtime, type_only)`` dotted targets. A target appearing in both is
        reported as runtime: one unguarded import is enough to execute it.
    """
    blocked = type_checking_guarded_nodes(module.tree) if guarded is None else guarded
    runtime: set[str] = set()
    type_only: set[str] = set()

    for node in ast.walk(module.tree):
        sink = type_only if id(node) in blocked else runtime
        if isinstance(node, ast.Import):
            sink.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            target = (
                resolve_relative_import(
                    node, module.name, is_package=module.is_package_init
                )
                if node.level
                else (node.module or "")
            )
            if not target:
                continue
            sink.add(target)
            # `from pkg import name` may be importing a SUBMODULE rather than a
            # symbol; the two are indistinguishable without resolving the
            # target, so both readings are recorded and the caller keeps
            # whichever names a real module.
            sink.update(f"{target}.{alias.name}" for alias in node.names)

    return frozenset(runtime), frozenset(type_only - runtime)


def imported_symbols(module: SourceModule) -> frozenset[tuple[str, str]]:
    """Return every ``(module, name)`` pair a module imports by name.

    Args:
        module: The module to read.

    Returns:
        Each ``from M import N`` pair, with ``M`` resolved to its absolute
        dotted form. This is the exact half of symbol reachability: a
        top-level name's only ways in are an import of its defining module, a
        use inside that module, or a string naming it.
    """
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        target = (
            resolve_relative_import(
                node, module.name, is_package=module.is_package_init
            )
            if node.level
            else (node.module or "")
        )
        if target:
            pairs.update((target, alias.name) for alias in node.names)
    return frozenset(pairs)


def is_shipped_module(name: str, package: str = PACKAGE) -> bool:
    """Return whether a dotted name addresses the shipped package.

    Args:
        name: The dotted name to test.
        package: The shipped package name.

    Returns:
        True for the package itself and anything beneath it.
    """
    return name == package or name.startswith(f"{package}.")


def repo_source_roots(repo_root: Path = REPO_ROOT) -> tuple[Path, ...]:
    """Return the trees outside the package that may consume it.

    Args:
        repo_root: The repository root.

    Returns:
        Each existing directory, in a stable order. These are this
        repository's own tooling and scripts: a package symbol they consume is
        load-bearing even though no installed user reaches it.
    """
    candidates = ("dev", "scripts", "packaging", "docs")
    return tuple(path for name in candidates if (path := repo_root / name).is_dir())


def alembic_script_location(repo_root: Path = REPO_ROOT) -> Path | None:
    """Return the directory Alembic loads migration scripts from.

    Args:
        repo_root: The repository root.

    Returns:
        The resolved directory, or ``None`` when the repository has no
        ``alembic.ini``.

    Two instruments need this and neither can afford to guess it. A migration
    revision is executed by Alembic reading this directory off the filesystem,
    so nothing imports it: the reachability audit must treat these modules as
    roots, and the loadability probe must not import them at all, because
    ``env.py`` reads ``alembic.context`` and that only exists inside a run.
    """
    config = repo_root / "alembic.ini"
    if not config.is_file():
        return None
    for line in config.read_text(encoding=UTF_8).splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "script_location" and value.strip():
            return (repo_root / value.strip()).resolve()
    return None
