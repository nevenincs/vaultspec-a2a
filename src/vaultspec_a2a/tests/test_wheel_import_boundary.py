"""No shipped module may import a package the wheel leaves behind.

``pyproject.toml`` excludes the test-execution machinery from the built wheel -
``testing/``, every ``tests`` tree, ``conftest.py``, ``desktop_tests``,
``service_tests``, ``acceptance`` - and its comment states the other half of the
bargain in prose: "Its only importers are the test trees excluded above." That
sentence is a cross-site invariant living in build configuration, where nothing
can enforce it.

The defect it describes is one a developer cannot see. A production module that
imports an excluded package resolves perfectly from a source checkout, because
the checkout contains the whole tree; it raises ``ImportError`` only once
installed from a wheel, where those files are absent. So the failure is
invisible exactly where the code is written and fatal exactly where nobody is
watching it run.

Three properties make this guard worth its weight where others in this campaign
were rejected:

- It asserts an INVARIANT, not a spelling. Renaming a helper, moving a module,
  or adding a new excluded package changes nothing about what it checks.
- The excluded set is DERIVED from ``pyproject.toml``, never restated here. A
  copy of the denylist would be a second declaration of the wheel's exclusion
  policy and would drift the first time someone edits the real one - which is
  the class of defect this campaign exists to remove, not to commit.
- It reads IMPORTS rather than importing. A guard that imported the modules
  would resolve them against this checkout and see exactly the tree that hides
  the problem.

Type-checking-only imports count. They do not break a wheel at runtime, but they
name a module an installed package cannot resolve, and the distance between a
guarded import and an unguarded one is a single edit.

The scan asserts what it visited. Source is read as BYTES and handed to the
parser, which honours a file's own encoding declaration rather than the
platform default, and the file and import counts are asserted so a scan that
died partway cannot return "no violations found" - on an exhaustiveness check, a
partial answer and a wrong answer are the same answer.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path, PurePosixPath

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _PACKAGE_ROOT.parent
_PROJECT_ROOT = _SOURCE_ROOT.parent
_DISTRIBUTION = _PACKAGE_ROOT.name

_MINIMUM_MODULES = 100
"""Floor on production modules scanned; the tree holds well over twice this."""

_MINIMUM_RESOLVED_IMPORTS = 500
"""Floor on intra-package imports the scan must resolve to real files.

A resolver that quietly stopped resolving anything would report no violations
and look identical to a clean tree. This is the assertion that tells them apart.
"""


def _wheel_exclusions() -> list[str]:
    """Return the wheel's exclude patterns, read from the build configuration.

    Read rather than restated: this is the project's single declaration of what
    the wheel leaves behind, and a guard carrying its own copy would enforce
    yesterday's policy against today's build.
    """
    pyproject = _PROJECT_ROOT / "pyproject.toml"
    assert pyproject.is_file(), (
        f"the build configuration must be readable at {pyproject}; without it "
        "this guard has no authority to derive the excluded set from"
    )
    configuration = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    wheel = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]
    patterns = wheel["exclude"]
    assert patterns, "the wheel declares no exclusions, so this guard is moot"
    return list(patterns)


def _shipped_modules() -> list[Path]:
    """Return every module the wheel ships, sorted.

    Shared by both tests below so the "what does the wheel exclude" judgement
    is computed once: two independent copies could pass one test and fail the
    other over a genuinely identical question.
    """
    patterns = _wheel_exclusions()
    sources = sorted(_PACKAGE_ROOT.rglob("*.py"))
    excluded = {
        path
        for path in sources
        if any(
            PurePosixPath(path.relative_to(_PROJECT_ROOT).as_posix()).full_match(
                pattern
            )
            for pattern in patterns
        )
    }
    return [path for path in sources if path not in excluded]


def _module_path(dotted: list[str]) -> tuple[Path, Path]:
    """Return the module-file and package-``__init__`` candidates for *dotted*."""
    base = _SOURCE_ROOT.joinpath(*dotted)
    return base.with_suffix(".py"), base / "__init__.py"


def _dotted_name(path: Path) -> list[str]:
    """Return the importable name of *path* as its segments."""
    parts = path.relative_to(_SOURCE_ROOT).with_suffix("").parts
    return list(parts[:-1] if parts[-1] == "__init__" else parts)


def _imported_targets(
    node: ast.Import | ast.ImportFrom, containing: list[str]
) -> list[list[str]]:
    """Return every distribution-internal module *node* could be importing.

    A ``from`` import names a module and then names things inside it, and those
    things may themselves be modules, so both readings are returned; a name that
    turns out to be a function simply resolves to no file.
    """
    if isinstance(node, ast.Import):
        return [alias.name.split(".") for alias in node.names]
    tail = node.module.split(".") if node.module else []
    if not node.level:
        module = tail
    else:
        # level 1 is the containing package; each further level climbs one more.
        anchor = containing[: len(containing) - (node.level - 1)]
        module = [*anchor, *tail]
    return [module, *([*module, alias.name] for alias in node.names)]


def test_no_shipped_module_imports_a_wheel_excluded_package() -> None:
    """Every module the wheel ships must resolve from the wheel alone."""
    sources = sorted(_PACKAGE_ROOT.rglob("*.py"))
    every_source = set(sources)
    shipped = _shipped_modules()
    excluded = every_source - set(shipped)

    resolved_imports = 0
    violations: list[str] = []
    for path in shipped:
        # Bytes, not text: the parser honours the file's own encoding
        # declaration, where a platform-default decode would raise on a source
        # file that is legal Python and abandon the scan mid-tree.
        tree = ast.parse(path.read_bytes(), filename=str(path))
        name = _dotted_name(path)
        containing = name if path.name == "__init__.py" else name[:-1]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            for target in _imported_targets(node, containing):
                if not target or target[0] != _DISTRIBUTION:
                    continue
                candidates = _module_path(target)
                if not any(candidate in every_source for candidate in candidates):
                    continue
                resolved_imports += 1
                if any(candidate in excluded for candidate in candidates):
                    site = path.relative_to(_PROJECT_ROOT).as_posix()
                    violations.append(
                        f"{site}:{node.lineno} imports {'.'.join(target)}"
                    )

    assert len(shipped) >= _MINIMUM_MODULES, (
        f"only {len(shipped)} shipped modules were scanned, which is fewer than "
        f"this distribution has; the scan did not reach the whole tree, and a "
        "partial exhaustiveness check reports no violations for the wrong reason"
    )
    assert resolved_imports >= _MINIMUM_RESOLVED_IMPORTS, (
        f"only {resolved_imports} internal imports resolved to real files, so "
        "the resolver is not doing its job; an empty violation list from a "
        "resolver that resolves nothing is indistinguishable from a clean tree"
    )
    listing = "\n  ".join(sorted(violations))
    assert not violations, (
        "these modules ship in the wheel but import packages the wheel excludes, "
        "so they resolve in a source checkout and raise ImportError once "
        f"installed:\n  {listing}\n\n"
        "The excluded set is derived from the exclude list under "
        "[tool.hatch.build.targets.wheel] in pyproject.toml. Move the shared "
        "mechanism into a package the wheel ships, or move the importing module "
        "out of the wheel - do not widen the exclusion list to make this pass, "
        "which trades a caught defect for a shipped one."
    )


_MINIMUM_CONSTANT_SCAN_MODULES = 100
"""Floor on shipped modules scanned for a wheel-excluded dotted name."""


def _wheel_excluded_module_stems() -> frozenset[str]:
    """Return the dotted-name stem of every package the wheel leaves behind.

    Derived from the SAME exclude patterns :func:`_wheel_exclusions` reads,
    never restated: a directory pattern becomes its dotted name
    (``src/vaultspec_a2a/testing`` -> ``vaultspec_a2a.testing``); the
    universal ``**/tests`` pattern becomes the bare final component
    ``tests``, because it excludes any package's OWN tests subpackage, not
    one fixed path.
    """
    stems: set[str] = set()
    prefix = f"src/{_DISTRIBUTION}/"
    for pattern in _wheel_exclusions():
        if pattern in ("**/tests", "**/tests/**"):
            stems.add("tests")
            continue
        if not pattern.startswith(prefix):
            continue
        trimmed = pattern.removeprefix(prefix).removesuffix("/**")
        if "." in trimmed:
            continue  # a specific excluded FILE (conftest.py, a preset), not a package
        stems.add(f"{_DISTRIBUTION}.{trimmed}")
    assert stems, "no package-shaped exclusion was derived from pyproject.toml"
    return frozenset(stems)


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    """Return the ``id()`` of every ``Constant`` node that is a real docstring.

    Checked by identity rather than value, so two identical docstrings do not
    make the scan below treat the second occurrence as exempt too.
    """
    ids: set[int] = set()
    scopes: list[ast.AST] = [tree]
    scopes.extend(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    )
    for scope in scopes:
        body: list[ast.stmt] = getattr(scope, "body", [])
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def test_no_shipped_module_names_a_wheel_excluded_package_as_a_string() -> None:
    """Close the dynamic-import bypass a static ``import`` scan cannot see (Q.5h).

    ``importlib.import_module("vaultspec_a2a.testing.something")`` never
    produces an :class:`ast.Import`/:class:`ast.ImportFrom` node, so the
    sibling test above - which reads only those two node types - is blind to
    it. This is the same invariant, read off every string constant instead,
    which is also why a docstring describing the architecture in prose (this
    very module's own docstring, for one) is exempt rather than flagged: Q.5h
    asks for the dynamic-import bypass, not for a ban on naming these packages
    at all.
    """
    excluded_components = {
        stem.rsplit(".", 1)[-1] for stem in _wheel_excluded_module_stems()
    }
    dotted_name = re.compile(
        rf"\b{re.escape(_DISTRIBUTION)}(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b"
    )
    shipped = _shipped_modules()

    violations: list[str] = []
    for path in shipped:
        tree = ast.parse(path.read_bytes(), filename=str(path))
        exempt = _docstring_constant_ids(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in exempt:
                continue
            for match in dotted_name.finditer(node.value):
                components = set(match.group(0).split(".")[1:])
                if excluded_components & components:
                    site = path.relative_to(_PROJECT_ROOT).as_posix()
                    violations.append(f"{site}:{node.lineno} names {match.group(0)!r}")
                    break

    assert len(shipped) >= _MINIMUM_CONSTANT_SCAN_MODULES, (
        f"only {len(shipped)} shipped modules were scanned; a partial scan "
        "reports no violations for the wrong reason"
    )
    assert not violations, (
        "these shipped modules spell a wheel-excluded package as a string "
        "constant outside a docstring, which is invisible to the "
        "import-statement scan above and breaks the same way once installed "
        "from the wheel:\n  " + "\n  ".join(sorted(violations))
    )
