#!/usr/bin/env python
"""Audit shipped code that no shipped entry point can ever reach.

The question here is narrower and stricter than the vulture scan in
:mod:`dev.audit.dead_code`: *starting from what the wheel installs, which
shipped modules are never imported, and which top-level symbols inside the
reachable modules are never referenced?*

Two layers are computed.

**Module reachability** walks the import graph from every ``[project.scripts]``
console script and every shipped ``__main__.py`` - ``python -m pkg.thing`` is
an execution surface an installed user has whether or not the packaging names
it. Static ``import``/``from`` statements are edges, and so is any string
literal naming a shipped module, because this repository binds a uvicorn
factory, a worker process target, and a pytest plugin by dotted name rather
than by import. Imports guarded by ``if TYPE_CHECKING:`` do not execute, so a
module reachable only through them is reported separately as ``type-only``.

**Symbol reachability** then looks inside the runtime-reachable modules, and
answers only the question it can answer exactly. A TOP-LEVEL function, class,
or constant has a closed set of ways in: an import of its defining module
(``from M import N``, or ``M.N`` through an import alias), a use inside its own
module, or a string naming it. A bare identifier load somewhere unrelated does
NOT clear it, which is the whole difference between this and a name-frequency
heuristic. Members - methods, attributes, enum members - are deliberately out
of scope: they have no defining-site import to resolve, so they stay a
bare-identifier question, which is exactly what vulture already answers.

Three asymmetries are load-bearing:

* **A decorator that is not merely shaping is a registration.** ``@app.get``,
  ``@app.command``, ``@field_validator`` reach a function without ever spelling
  its name. Everything outside :data:`PLAIN_DECORATORS` therefore clears a
  symbol - which is the false-positive class that makes the raw vulture output
  over this tree almost entirely noise.
* **A reference from a test is not use.** A symbol kept alive only by its own
  unit test is the orphan signal this audit exists to surface, so ``used by:
  tests`` LABELS a finding without clearing it.
* **A reference from ``dev/`` clears a SYMBOL but not a MODULE.** ``dev/`` is
  this repository's own harness; a package symbol the harness consumes is
  load-bearing, and deleting it breaks a gate rather than shrinking the wheel.
  A whole shipped module only ``dev/`` imports really is bytes every installed
  user carries and none reaches, which is worth keeping visible.

The scan is static and read-only. It never imports the production package.

See Also:
    :mod:`dev.audit.dead_code`
        The heuristic vulture runner; it models no entry point at all.
    :mod:`dev.quality.unreachable_module_coverage`
        The zero-target gate over this audit's module findings.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from dev.exit_codes import ADVISORY_BROKEN, OK
from dev.paths import PACKAGE, PACKAGE_ROOT, REPO_ROOT, SRC_ROOT, UTF_8, repo_relative
from dev.quality.source_import_analysis import (
    SourceModule,
    UnreadableSourceError,
    imported_modules,
    imported_symbols,
    load_modules,
    parse_module,
    repo_source_roots,
    type_checking_guarded_nodes,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from pathlib import Path

#: How many findings of each kind the console report names before it caps.
FINDING_CAP: Final[int] = 40

#: Decorators that merely shape a definition. Anything else is read as a
#: framework registration that reaches the symbol without naming it.
PLAIN_DECORATORS: Final[frozenset[str]] = frozenset(
    {
        "abstractmethod",
        "cached_property",
        "classmethod",
        "dataclass",
        "final",
        "overload",
        "override",
        "property",
        "staticmethod",
    },
)

#: Non-Python files scanned for dotted module and symbol names. This
#: repository names its process targets in ``procs.toml`` and its console
#: script in ``pyproject.toml``; a module reached only from there is live.
DATA_FILES: Final[tuple[str, ...]] = ("pyproject.toml", "procs.toml", "conftest.py")

#: Identifier-shaped tokens, used to read names out of non-Python text.
DATA_TOKEN: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{2,}")

#: Module-level names that are never findings: they are the interpreter's or a
#: packaging tool's, not this repository's to consume.
EXEMPT_NAMES: Final[frozenset[str]] = frozenset({"__all__", "main"})


class UnreachableCodeOutcome(StrEnum):
    """The three honest states the scan can land in."""

    CLEAN = "clean"
    FINDINGS = "findings"
    ERROR = "error"


class ModuleReach(StrEnum):
    """How a shipped module is reached, if at all."""

    #: Imported, directly or transitively, by something an installed user runs.
    RUNTIME = "runtime"
    #: Reached only through ``if TYPE_CHECKING:`` imports, which never execute.
    TYPE_ONLY = "type-only"
    #: Reached by nothing an installed user runs.
    UNREACHABLE = "unreachable"


class SymbolKind(StrEnum):
    """What kind of top-level definition a symbol finding names."""

    FUNCTION = "function"
    CLASS = "class"
    CONSTANT = "constant"


@dataclass(frozen=True, slots=True, order=True)
class ModuleFinding:
    """One shipped module no installed user reaches.

    Args:
        module: The dotted module name.
        path: Repository-relative path.
        reach: How it is reached, if at all.
        used_by: Labels for the corpora that DO reference it.
    """

    module: str
    path: str
    reach: ModuleReach
    used_by: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, order=True)
class SymbolFinding:
    """One top-level symbol nothing shipped references.

    Args:
        module: The dotted module that defines it.
        path: Repository-relative path.
        line: One-based line of the definition.
        name: The symbol's name.
        kind: What kind of definition it is.
        used_by: Labels for the corpora that DO reference it.
    """

    module: str
    path: str
    line: int
    name: str
    kind: SymbolKind
    used_by: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, order=True)
class TestFinding:
    """One test module whose every shipped subject is itself a finding.

    Args:
        module: The dotted module name.
        path: Repository-relative path.
        subjects: The findings it exercises, as dotted names.
    """

    module: str
    path: str
    subjects: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UnreachableCodeResult:
    """The whole scan's typed outcome.

    Args:
        outcome: Which of the three states the scan landed in.
        modules: Every module finding.
        symbols: Every symbol finding.
        tests: Every orphaned-test finding.
        modules_scanned: How many shipped modules were read.
        entry_points: The roots the walk started from.
        reason: Why the scan could not run, when it could not.
    """

    outcome: UnreachableCodeOutcome
    modules: tuple[ModuleFinding, ...] = ()
    symbols: tuple[SymbolFinding, ...] = ()
    tests: tuple[TestFinding, ...] = ()
    modules_scanned: int = 0
    entry_points: tuple[str, ...] = ()
    reason: str = ""

    @classmethod
    def error(cls, reason: str) -> UnreachableCodeResult:
        """Build the outcome of a scan that produced no trustworthy result.

        Args:
            reason: What went wrong, in one clause.

        Returns:
            The error result.
        """
        return cls(outcome=UnreachableCodeOutcome.ERROR, reason=reason)

    @property
    def finding_count(self) -> int:
        """How many findings the scan produced, across all three layers."""
        return len(self.modules) + len(self.symbols) + len(self.tests)

    def headline(self) -> str:
        """Render the one-line human summary of the outcome."""
        if self.outcome is UnreachableCodeOutcome.ERROR:
            return f"signal unavailable this cycle: {self.reason}"
        if self.outcome is UnreachableCodeOutcome.CLEAN:
            return (
                f"every one of {self.modules_scanned} shipped module(s) is reachable "
                f"from {len(self.entry_points)} entry point(s)"
            )
        return (
            f"{len(self.modules)} unreachable module(s), {len(self.symbols)} unused "
            f"symbol(s), {len(self.tests)} orphaned test(s) across "
            f"{self.modules_scanned} shipped module(s)"
        )


@dataclass(frozen=True, slots=True)
class ShippedTreeSpec:
    """Where the tree under analysis lives.

    Args:
        repo_root: The repository root.
        src_root: The import root the package is built from.
        package_root: The shipped package's directory.
        package: The shipped package's import name.
    """

    repo_root: Path = REPO_ROOT
    src_root: Path = SRC_ROOT
    package_root: Path = PACKAGE_ROOT
    package: str = PACKAGE


@dataclass(slots=True)
class _Corpus:
    """Everything one scan reads, parsed once.

    Args:
        shipped: Every module in the shipped package.
        outside: Every module in this repository's own tooling trees.
        data_text: The concatenated text of the scanned non-Python files.
    """

    shipped: dict[str, SourceModule]
    outside: dict[str, SourceModule]
    data_text: str = ""
    string_tokens: frozenset[str] = field(default_factory=frozenset)


# ---------------------------------------------------------------------------
#  Entry points
# ---------------------------------------------------------------------------


def console_script_modules(spec: ShippedTreeSpec) -> tuple[str, ...]:
    """Read the modules the wheel's console scripts land in.

    Args:
        spec: Where the tree lives.

    Returns:
        Each ``[project.scripts]`` target's module, in stable order.

    Raises:
        UnreadableSourceError: When ``pyproject.toml`` cannot be read, which
            would otherwise silently leave the walk with no roots and report
            the entire package unreachable.
    """
    manifest = spec.repo_root / "pyproject.toml"
    try:
        payload = tomllib.loads(manifest.read_text(encoding=UTF_8))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        msg = f"{manifest} could not be read: {exc}"
        raise UnreadableSourceError(msg) from exc

    scripts = payload.get("project", {}).get("scripts", {})
    return tuple(sorted({str(target).partition(":")[0] for target in scripts.values()}))


def module_execution_surfaces(shipped: dict[str, SourceModule]) -> tuple[str, ...]:
    """Return every module an installed user can run with ``python -m``.

    Args:
        shipped: Every shipped module.

    Returns:
        Each ``__main__`` module's dotted name, in stable order.
    """
    return tuple(
        sorted(
            name
            for name, module in shipped.items()
            if module.path.name == "__main__.py"
        )
    )


def migration_surfaces(
    spec: ShippedTreeSpec,
    shipped: dict[str, SourceModule],
) -> tuple[str, ...]:
    """Return every module Alembic loads by path rather than by import.

    Args:
        spec: Where the tree lives.
        shipped: Every shipped module.

    Returns:
        Each module under ``alembic.ini``'s ``script_location``, in stable
        order, or nothing when no such config exists.

    A migration revision is executed by Alembic reading the ``versions/``
    directory off the filesystem; no line of Python anywhere imports it. The
    import graph therefore cannot see it, and without this every revision in
    the tree reads as unreachable - which is 21 findings that would be wrong
    every time and would teach a reader to skim the list.
    """
    config = spec.repo_root / "alembic.ini"
    if not config.is_file():
        return ()
    location = ""
    for line in config.read_text(encoding=UTF_8).splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "script_location":
            location = value.strip()
            break
    if not location:
        return ()

    root = (spec.repo_root / location).resolve()
    return tuple(
        sorted(
            name
            for name, module in shipped.items()
            if root in module.path.resolve().parents
        )
    )


def configured_surfaces(
    spec: ShippedTreeSpec, shipped: dict[str, SourceModule]
) -> tuple[str, ...]:
    """Return every shipped module this repository's own configuration names.

    Args:
        spec: Where the tree lives.
        shipped: Every shipped module.

    Returns:
        Each named module, in stable order.

    ``procs.toml`` names the worker's process target and the repository-root
    ``conftest.py`` loads the shipped pytest plugin - both by dotted string,
    neither through an import. A module a running surface is configured to
    load is reached, whatever the import graph says.

    The package's own name does NOT count. It appears in ``pyproject.toml``
    by definition - as the distribution name, in the wheel's package list, in
    every tool's configuration - and admitting it would make the package root
    an entry point in every repository, which turns whatever that ``__init__``
    imports into reachable code for no reason anyone stated.
    """
    text = _read_data_text(spec)
    named = {token.partition(":")[0] for token in DATA_TOKEN.findall(text)}
    return tuple(sorted((named & set(shipped)) - {spec.package}))


def entry_points(
    spec: ShippedTreeSpec, shipped: dict[str, SourceModule]
) -> tuple[str, ...]:
    """Return every root the reachability walk starts from.

    Args:
        spec: Where the tree lives.
        shipped: Every shipped module.

    Returns:
        The console scripts, the ``python -m`` surfaces, the Alembic revision
        modules, and the modules named by this repository's configuration,
        deduped.

    Raises:
        UnreadableSourceError: As :func:`console_script_modules`.
    """
    roots = (
        set(console_script_modules(spec))
        | set(module_execution_surfaces(shipped))
        | set(migration_surfaces(spec, shipped))
        | set(configured_surfaces(spec, shipped))
    )
    return tuple(sorted(root for root in roots if root in shipped))


# ---------------------------------------------------------------------------
#  Module reachability
# ---------------------------------------------------------------------------


def _string_constants(tree: ast.Module) -> Iterator[str]:
    """Yield every string constant in a module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def string_module_edges(tree: ast.Module, known: frozenset[str]) -> frozenset[str]:
    """Return the shipped modules a module names in a string literal.

    Args:
        tree: The parsed module.
        known: Every shipped module name.

    Returns:
        The named modules. A dotted string is how this repository binds a
        uvicorn factory, a worker process target, and its pytest plugin, so a
        module reached only that way is live and must not read as dead.
    """
    found: set[str] = set()
    for value in _string_constants(tree):
        head = value.partition(":")[0].strip()
        if head in known:
            found.add(head)
    return frozenset(found)


def module_edges(
    module: SourceModule,
    known: frozenset[str],
) -> tuple[frozenset[str], frozenset[str]]:
    """Return one module's runtime and type-only edges into the shipped tree.

    Args:
        module: The module to read.
        known: Every shipped module name.

    Returns:
        ``(runtime, type_only)`` dotted targets, restricted to shipped modules.
    """
    runtime, type_only = imported_modules(module)
    strings = string_module_edges(module.tree, known)
    return (
        frozenset(name for name in runtime | strings if name in known),
        frozenset(name for name in type_only if name in known) - strings,
    )


def _ancestors(name: str) -> Iterator[str]:
    """Yield a dotted name's package ancestors, nearest first."""
    parts = name.split(".")
    for stop in range(len(parts) - 1, 0, -1):
        yield ".".join(parts[:stop])


def reachable_closure(
    roots: Sequence[str],
    edges: dict[str, frozenset[str]],
    known: frozenset[str],
) -> frozenset[str]:
    """Walk the import graph from ``roots``.

    Args:
        roots: The modules the walk starts from.
        edges: Each module's outgoing edges.
        known: Every shipped module name.

    Returns:
        Every module reached. Importing ``a.b.c`` executes ``a`` and ``a.b``,
        so each reached module's package ancestors are reached with it.
    """
    seen: set[str] = set()
    queue = deque(roots)
    while queue:
        name = queue.popleft()
        if name in seen or name not in known:
            continue
        seen.add(name)
        queue.extend(edges.get(name, frozenset()))
        queue.extend(ancestor for ancestor in _ancestors(name) if ancestor in known)
    return frozenset(seen)


def classify_modules(
    corpus: _Corpus,
    roots: Sequence[str],
) -> tuple[dict[str, ModuleReach], dict[str, frozenset[str]]]:
    """Classify every shipped non-test module by how it is reached.

    Args:
        corpus: The parsed corpus.
        roots: The entry-point modules.

    Returns:
        ``(reach, runtime_edges)`` - the classification per module, and the
        runtime edge map, which the orphan-test layer reuses.
    """
    known = frozenset(corpus.shipped)
    runtime: dict[str, frozenset[str]] = {}
    combined: dict[str, frozenset[str]] = {}
    for name, module in corpus.shipped.items():
        run, typed = module_edges(module, known)
        runtime[name] = run
        combined[name] = run | typed

    # A test module is not an entry point, but it is shipped, so its imports
    # keep nothing alive: the walk starts at the entry points alone.
    at_runtime = reachable_closure(roots, runtime, known)
    at_any = reachable_closure(roots, combined, known)

    reach: dict[str, ModuleReach] = {}
    for name, module in corpus.shipped.items():
        if module.is_test:
            continue
        if name in at_runtime:
            reach[name] = ModuleReach.RUNTIME
        elif name in at_any:
            reach[name] = ModuleReach.TYPE_ONLY
        else:
            reach[name] = ModuleReach.UNREACHABLE
    return reach, runtime


def _referencing_corpora(corpus: _Corpus) -> dict[str, frozenset[str]]:
    """Return, per corpus label, every shipped module that corpus references.

    Args:
        corpus: The parsed corpus.

    Returns:
        ``{"tests": ..., "dev": ...}``. Computed once for the whole scan: the
        per-finding form of this walked the entire corpus for every finding,
        which is quadratic in a tree of 800 modules.
    """
    known = frozenset(corpus.shipped)
    tests: set[str] = set()
    dev: set[str] = set()
    for module in corpus.shipped.values():
        if module.is_test:
            runtime, typed = module_edges(module, known)
            tests |= runtime | typed
    for module in corpus.outside.values():
        runtime, typed = module_edges(module, known)
        dev |= runtime | typed
    return {"tests": frozenset(tests), "dev": frozenset(dev)}


def _module_labels(
    name: str,
    referencing: dict[str, frozenset[str]],
    configured: frozenset[str],
) -> tuple[str, ...]:
    """Return the corpora that reference a module without making it reachable.

    Args:
        name: The module's dotted name.
        referencing: The per-label reference map.
        configured: Module names this repository's configuration mentions.

    Returns:
        The labels, in a fixed order so two runs render identically.
    """
    labels = [label for label in ("tests", "dev") if name in referencing[label]]
    if name in configured:
        labels.append("config")
    return tuple(labels)


# ---------------------------------------------------------------------------
#  Symbol reachability
# ---------------------------------------------------------------------------


def _decorator_name(node: ast.expr) -> str:
    """Return the base name of a decorator expression."""
    target = node.func if isinstance(node, ast.Call) else node
    while isinstance(target, ast.Attribute):
        target = target.value
    if isinstance(target, ast.Attribute | ast.Name):
        return target.id if isinstance(target, ast.Name) else target.attr
    return ""


def _is_framework_bound(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> bool:
    """Return whether a decorator reaches this definition without naming it.

    Args:
        node: The decorated definition.

    Returns:
        True when any decorator is something other than a plain shaping one.
        ``@app.get("/health")`` registers the handler with a router; the
        handler's name then appears exactly once in the tree, and reading that
        as dead is the single largest false-positive class over this tree.
    """
    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and _decorator_name(decorator) not in PLAIN_DECORATORS
        ):
            return True
        if (
            not isinstance(decorator, ast.Call)
            and _decorator_name(decorator) not in PLAIN_DECORATORS
        ):
            return True
    return False


@dataclass(frozen=True, slots=True)
class _Definition:
    """One top-level definition in a shipped module."""

    name: str
    line: int
    kind: SymbolKind
    framework_bound: bool


def top_level_definitions(tree: ast.Module) -> Iterator[_Definition]:
    """Yield every top-level definition in a module.

    Args:
        tree: The parsed module.

    Yields:
        Each function, class, and module-level constant assignment. Dunders
        and the names in :data:`EXEMPT_NAMES` are skipped: they are addressed
        by the interpreter or by packaging, not by this repository's code.
    """
    for node in tree.body:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                kind = SymbolKind.FUNCTION
            case ast.ClassDef():
                kind = SymbolKind.CLASS
            case ast.Assign() | ast.AnnAssign():
                yield from _constant_definitions(node)
                continue
            case _:
                continue
        if node.name.startswith("__") or node.name in EXEMPT_NAMES:
            continue
        yield _Definition(node.name, node.lineno, kind, _is_framework_bound(node))


def _constant_definitions(node: ast.Assign | ast.AnnAssign) -> Iterator[_Definition]:
    """Yield the module-level constants one assignment statement binds."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    for target in targets:
        if not isinstance(target, ast.Name) or target.id.startswith("__"):
            continue
        if target.id in EXEMPT_NAMES:
            continue
        yield _Definition(
            target.id, node.lineno, SymbolKind.CONSTANT, framework_bound=False
        )


def _export_list(tree: ast.Module) -> ast.List | ast.Tuple | None:
    """Return the literal a module assigns to ``__all__``, when it has one."""
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(
            node.value, ast.List | ast.Tuple
        ):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            return node.value
    return None


def declared_exports(tree: ast.Module) -> frozenset[str]:
    """Return the names a module lists in ``__all__``.

    Args:
        tree: The parsed module.

    Returns:
        Every exported name, or an empty set when the module declares none.
    """
    literal = _export_list(tree)
    if literal is None:
        return frozenset()
    return frozenset(
        element.value
        for element in literal.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    )


def self_references(module: SourceModule) -> frozenset[str]:
    """Return the names a module references inside itself.

    Args:
        module: The module to read.

    Returns:
        Every identifier the module loads and every token in its string
        literals - but NOT the strings inside its own ``__all__`` list.

        The exclusion is scoped to that one literal on purpose. Listing a name
        in ``__all__`` publishes it; it is not a use, and counting it as one
        would make every exported symbol self-clearing and the whole layer
        vacuous. Subtracting the exported NAMES from the whole reference set
        instead - which is how this was first written - throws away the real
        loads too, and reported ``gateway_bearer_scheme`` as unused while
        ``Depends(gateway_bearer_scheme)`` sat twelve lines below it.
    """
    literal = _export_list(module.tree)
    exported_strings = (
        frozenset(id(element) for element in literal.elts) if literal else frozenset()
    )

    names: set[str] = set()
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in exported_strings:
                continue
            names.update(DATA_TOKEN.findall(node.value))
    return frozenset(names)


def _consumers(
    corpus: _Corpus,
) -> tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    """Return the ``(module, name)`` pairs shipped and outside code imports.

    Args:
        corpus: The parsed corpus.

    Returns:
        ``(shipped_non_test, labelled)`` where the second maps a pair to the
        corpora - tests, dev - that import it without clearing it outright.
    """
    shipped_use: set[tuple[str, str]] = set()
    test_use: set[tuple[str, str]] = set()
    for module in corpus.shipped.values():
        (test_use if module.is_test else shipped_use).update(imported_symbols(module))
    return frozenset(shipped_use), frozenset(test_use)


def _attribute_names(modules: Iterable[SourceModule]) -> frozenset[str]:
    """Return every name a corpus reads as an attribute.

    Args:
        modules: The modules to read.

    Returns:
        Each attribute name. This is a LABELLING signal only, never a clearing
        one: ``module.ARTIFACT_DECLARATIONS`` in a reflective test reaches a
        symbol without importing it by name, and a reader deserves to be told
        that the only thing reaching a finding is a test - but an attribute
        name matches by spelling alone, so it can never clear one.
    """
    names: set[str] = set()
    for module in modules:
        names.update(
            node.attr
            for node in ast.walk(module.tree)
            if isinstance(node, ast.Attribute)
        )
    return frozenset(names)


def find_symbol_findings(
    corpus: _Corpus,
    reach: dict[str, ModuleReach],
    convention_bound: frozenset[str] = frozenset(),
) -> tuple[SymbolFinding, ...]:
    """Find every top-level symbol nothing shipped or tooling-side references.

    Args:
        corpus: The parsed corpus.
        reach: Each module's reachability classification.
        convention_bound: Modules whose top-level names are a framework's
            contract rather than this repository's. An Alembic revision's
            ``revision``, ``down_revision``, ``upgrade`` and ``downgrade`` are
            read off the module object by the migration runner; nothing in the
            tree names them, and reporting all four for every revision is six
            findings apiece that are wrong every time.

    Returns:
        Every finding, in stable order. Only RUNTIME modules are inspected: a
        symbol inside an unreachable module is already covered by that
        module's own finding, and reporting both doubles one defect.
    """
    shipped_use, test_use = _consumers(corpus)
    dev_use = (
        frozenset().union(*(imported_symbols(m) for m in corpus.outside.values()))
        if corpus.outside
        else frozenset()
    )
    test_attrs = _attribute_names(m for m in corpus.shipped.values() if m.is_test)
    dev_attrs = _attribute_names(corpus.outside.values())

    findings: list[SymbolFinding] = []
    for name, module in corpus.shipped.items():
        if reach.get(name) is not ModuleReach.RUNTIME or name in convention_bound:
            continue
        own = self_references(module)
        for definition in top_level_definitions(module.tree):
            pair = (name, definition.name)
            if definition.framework_bound or definition.name in own:
                continue
            if (
                pair in shipped_use
                or pair in dev_use
                or definition.name in corpus.string_tokens
            ):
                continue
            labels = [
                label
                for label, pairs, attrs in (
                    ("tests", test_use, test_attrs),
                    ("dev", dev_use, dev_attrs),
                )
                if pair in pairs or definition.name in attrs
            ]
            findings.append(
                SymbolFinding(
                    module=name,
                    path=repo_relative(module.path),
                    line=definition.line,
                    name=definition.name,
                    kind=definition.kind,
                    used_by=tuple(labels),
                ),
            )
    return tuple(sorted(findings))


# ---------------------------------------------------------------------------
#  Orphaned tests
# ---------------------------------------------------------------------------


def find_orphan_tests(
    corpus: _Corpus,
    dead_modules: frozenset[str],
    dead_symbols: frozenset[tuple[str, str]],
) -> tuple[TestFinding, ...]:
    """Find test modules whose every shipped subject is itself a finding.

    Args:
        corpus: The parsed corpus.
        dead_modules: The modules reported unreachable.
        dead_symbols: The ``(module, name)`` pairs reported unused.

    Returns:
        Every orphaned-test finding, in stable order. A test whose subjects
        are all dead exists only to exercise dead code, and is reported so the
        code and its tests can be retired together.
    """
    known = frozenset(corpus.shipped)
    findings: list[TestFinding] = []
    for name, module in corpus.shipped.items():
        if not module.is_test:
            continue
        runtime, typed = module_edges(module, known)
        subject_modules = {m for m in runtime | typed if not corpus.shipped[m].is_test}
        subject_symbols = {
            pair for pair in imported_symbols(module) if pair[0] in known
        }
        if not subject_modules and not subject_symbols:
            continue
        dead = {m for m in subject_modules if m in dead_modules}
        # A symbol inside a dead module is dead whether or not it appears in
        # the symbol findings - the symbol layer only inspects RUNTIME
        # modules, so nothing there ever names it. Without this clause a test
        # importing one function from an unreachable module reads as having a
        # live subject, and the clearest orphan there is goes unreported.
        dead |= {
            f"{m}.{n}"
            for m, n in subject_symbols
            if (m, n) in dead_symbols or m in dead_modules
        }
        live = len(subject_modules) + len(subject_symbols) - len(dead)
        if live:
            continue
        findings.append(
            TestFinding(
                module=name,
                path=repo_relative(module.path),
                subjects=tuple(sorted(dead)),
            ),
        )
    return tuple(sorted(findings))


# ---------------------------------------------------------------------------
#  The scan
# ---------------------------------------------------------------------------


def _read_data_text(spec: ShippedTreeSpec) -> str:
    """Return the concatenated text of the scanned non-Python files."""
    chunks: list[str] = []
    for name in DATA_FILES:
        path = spec.repo_root / name
        if path.is_file():
            chunks.append(path.read_text(encoding=UTF_8, errors="replace"))
    return "\n".join(chunks)


def _load_corpus(spec: ShippedTreeSpec) -> _Corpus:
    """Parse the shipped package, this repository's tooling, and its config."""
    shipped = load_modules(spec.package_root, src_root=spec.src_root)
    outside: dict[str, SourceModule] = {}
    for root in repo_source_roots(spec.repo_root):
        outside.update(load_modules(root, src_root=spec.repo_root))

    data_text = _read_data_text(spec)
    tokens = set(DATA_TOKEN.findall(data_text))
    # A dotted name in config addresses its own tail too: `procs.toml` naming
    # `vaultspec_a2a.worker` must keep `worker` from reading as an unused name
    # in its parent package.
    tokens.update(part for token in tuple(tokens) for part in token.split("."))
    return _Corpus(
        shipped=shipped,
        outside=outside,
        data_text=data_text,
        string_tokens=frozenset(tokens),
    )


def scan_unreachable_code(spec: ShippedTreeSpec | None = None) -> UnreachableCodeResult:
    """Run the whole reachability scan.

    Args:
        spec: Where the tree lives, or ``None`` for this repository.

    Returns:
        The typed result. A tree that cannot be parsed, or one whose entry
        points cannot be resolved, is reported as ERROR rather than as a tree
        in which everything happens to be reachable.
    """
    spec = spec or ShippedTreeSpec()
    try:
        corpus = _load_corpus(spec)
        roots = entry_points(spec, corpus.shipped)
    except UnreadableSourceError as exc:
        return UnreachableCodeResult.error(str(exc))

    if not roots:
        return UnreachableCodeResult.error(
            "no entry point resolved to a shipped module, so every module would "
            "read as unreachable",
        )

    reach, _ = classify_modules(corpus, roots)
    referencing = _referencing_corpora(corpus)
    configured = frozenset(configured_surfaces(spec, corpus.shipped))
    module_findings = tuple(
        sorted(
            ModuleFinding(
                module=name,
                path=repo_relative(corpus.shipped[name].path),
                reach=value,
                used_by=_module_labels(name, referencing, configured),
            )
            for name, value in reach.items()
            if value is not ModuleReach.RUNTIME
        ),
    )
    symbol_findings = find_symbol_findings(
        corpus,
        reach,
        frozenset(migration_surfaces(spec, corpus.shipped)),
    )
    test_findings = find_orphan_tests(
        corpus,
        frozenset(finding.module for finding in module_findings),
        frozenset((finding.module, finding.name) for finding in symbol_findings),
    )

    scanned = sum(1 for module in corpus.shipped.values() if not module.is_test)
    findings = bool(module_findings or symbol_findings or test_findings)
    return UnreachableCodeResult(
        outcome=UnreachableCodeOutcome.FINDINGS
        if findings
        else UnreachableCodeOutcome.CLEAN,
        modules=module_findings,
        symbols=symbol_findings,
        tests=test_findings,
        modules_scanned=scanned,
        entry_points=roots,
    )


def run_unreachable_code_scan(repo_root: Path = REPO_ROOT) -> UnreachableCodeResult:
    """Run the scan against a repository root.

    Args:
        repo_root: The repository to scan.

    Returns:
        The typed result. This is the entry point every consumer calls.
    """
    spec = ShippedTreeSpec(
        repo_root=repo_root,
        src_root=repo_root / "src",
        package_root=repo_root / "src" / PACKAGE,
    )
    return scan_unreachable_code(spec)


# ---------------------------------------------------------------------------
#  Reporting
# ---------------------------------------------------------------------------


def _used_by(labels: tuple[str, ...]) -> str:
    """Render a finding's used-by labels, or nothing when it has none."""
    return f"  [used by: {', '.join(labels)}]" if labels else ""


def _capped[T](
    items: tuple[T, ...], *, full: bool, cap: int
) -> tuple[tuple[T, ...], int]:
    """Return the items to show and how many were withheld."""
    shown = items if full else items[:cap]
    return shown, len(items) - len(shown)


def render_console_report(
    result: UnreachableCodeResult,
    *,
    full: bool = False,
    cap: int = FINDING_CAP,
) -> str:
    """Render the operator-facing console report.

    Args:
        result: The scan result.
        full: List every finding rather than the first ``cap`` of each kind.
        cap: How many findings of each kind to list when ``full`` is not set.

    Returns:
        The report text.
    """
    lines = [f"reachability: {result.headline()}"]
    if result.outcome is not UnreachableCodeOutcome.FINDINGS:
        return lines[0]

    modules, withheld = _capped(result.modules, full=full, cap=cap)
    if modules:
        lines.append(f"\nunreachable modules ({len(result.modules)}):")
        lines += [
            f"  {f.module}  ({f.reach.value}; {f.path}){_used_by(f.used_by)}"
            for f in modules
        ]
        if withheld:
            lines.append(f"  ... {withheld} more (--full for all)")

    symbols, withheld = _capped(result.symbols, full=full, cap=cap)
    if symbols:
        lines.append(f"\nunused top-level symbols ({len(result.symbols)}):")
        lines += [
            f"  {f.path}:{f.line}  {f.kind.value} {f.name}{_used_by(f.used_by)}"
            for f in symbols
        ]
        if withheld:
            lines.append(f"  ... {withheld} more (--full for all)")

    tests, withheld = _capped(result.tests, full=full, cap=cap)
    if tests:
        lines.append(f"\norphaned tests ({len(result.tests)}):")
        lines += [f"  {f.path}  (subjects: {', '.join(f.subjects)})" for f in tests]
        if withheld:
            lines.append(f"  ... {withheld} more (--full for all)")

    return "\n".join(lines)


def result_as_json(result: UnreachableCodeResult) -> str:
    """Render the scan result as the machine-readable report.

    Args:
        result: The scan result.

    Returns:
        The JSON document.
    """
    return json.dumps(
        {
            "outcome": result.outcome.value,
            "headline": result.headline(),
            "modules_scanned": result.modules_scanned,
            "entry_points": list(result.entry_points),
            "reason": result.reason,
            "modules": [
                {
                    "module": f.module,
                    "path": f.path,
                    "reach": f.reach.value,
                    "used_by": list(f.used_by),
                }
                for f in result.modules
            ],
            "symbols": [
                {
                    "module": f.module,
                    "path": f.path,
                    "line": f.line,
                    "name": f.name,
                    "kind": f.kind.value,
                    "used_by": list(f.used_by),
                }
                for f in result.symbols
            ],
            "tests": [
                {"module": f.module, "path": f.path, "subjects": list(f.subjects)}
                for f in result.tests
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the reachability scan and print its report.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        :data:`OK` when the scan ran, findings and all, and
        :data:`ADVISORY_BROKEN` when it could not.
    """
    parser = argparse.ArgumentParser(
        description="Audit shipped code no shipped entry point reaches.",
    )
    parser.add_argument(
        "--full", action="store_true", help="List every finding, uncapped."
    )
    parser.add_argument("--json", action="store_true", help="Emit the result as JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = run_unreachable_code_scan()
    report = (
        result_as_json(result)
        if args.json
        else render_console_report(result, full=args.full)
    )
    print(report)
    if result.outcome is UnreachableCodeOutcome.ERROR:
        print(result.reason, file=sys.stderr)
        return ADVISORY_BROKEN
    return OK


if __name__ == "__main__":
    raise SystemExit(main())


# `parse_module` and `type_checking_guarded_nodes` are re-exported for the
# coverage gates that build on this audit without reaching past it into the
# shared analysis module.
__all__ = [
    "ModuleFinding",
    "ModuleReach",
    "ShippedTreeSpec",
    "SymbolFinding",
    "SymbolKind",
    "TestFinding",
    "UnreachableCodeOutcome",
    "UnreachableCodeResult",
    "parse_module",
    "run_unreachable_code_scan",
    "scan_unreachable_code",
    "type_checking_guarded_nodes",
]
