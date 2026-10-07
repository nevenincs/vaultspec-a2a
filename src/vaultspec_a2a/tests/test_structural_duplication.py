"""No NEW substantial function may be a structural copy of another.

The sibling canonical-homes suite pins concepts by NAME, which is exactly where
it is blind: a clone written under a different name is invisible to it, and to
grep, and to semantic search, all three of which key on what something is
called. Two such clones were found in ``providers/`` only after a scan that
erases every identifier and compares what is left - the SHAPE of the code.

That scan is the reason this file exists. Run once it is an audit; run on every
commit it is the only check here that can catch a copy nobody has named yet.

How it works: each function body is parsed, stripped of its docstring, rewritten
so every identifier becomes the same placeholder, and hashed. Functions whose
bodies survive that erasure identically are structural duplicates regardless of
their names, their arguments, or the types they mention.

The scan covers the shipped package (``src/vaultspec_a2a``) AND the
repository's own tooling - ``dev/``, ``packaging/``, ``scripts/`` and the root
``conftest.py`` - because a copy-pasted fixture or guard is exactly as much
debt as one in the shipped package, and the tooling trees are large enough
(dev/ alone carries dozens of modules) to have grown their own clones unseen.
Tier classification mirrors :mod:`dev.paths` (``TEST_TIERS`` plus the
``testing`` support package) rather than importing it: a module inside the
distribution root may never import the development harness (see
``test_dev_harness_import_boundary.py``), and this file sits inside it.

Two limits are deliberate and worth knowing before reading a failure:

- It cannot see a clone that DIVERGED. A copy that gained one argument hashes
  differently and passes here. Finding those needs semantic search; the two
  methods are complements, and neither alone supports a claim that a concept
  has exactly one home.
- It flags THIN BINDING SHIMS, which is why the size floor exists. Consolidated
  code often leaves a small per-caller wrapper that binds local constants to a
  shared implementation, and those wrappers are structurally identical to each
  other by construction. They are the SUCCESS of a consolidation, not a
  failure of one, so the floor keeps them out rather than teaching people to
  ignore this suite.

Adding to the allowlist is a normal outcome, but an entry needs a REASON, not
just a recording. "Same module, one differing constant" is a legitimate reason:
naming two operations explicitly can beat one function with a parameter that
hides which column, table, or event kind is in play. "I did not have time to
merge these" is a reason too - written down, it stays visible instead of
becoming silent debt.
"""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, override

_SOURCE_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT: Final[Path] = _SOURCE_ROOT.parents[1]

#: Mirrors dev.paths.TEST_TIERS / TEST_SUPPORT, restated rather than imported
#: (see the module docstring's note on the harness import boundary).
_TEST_TIERS: Final[tuple[str, ...]] = (
    "tests",
    "service_tests",
    "desktop_tests",
    "acceptance",
)
_TEST_SUPPORT: Final = "testing"

#: Mirrors dev.paths.SKIPPED_DIRS, restated for the same reason.
_SKIPPED_DIRS: Final[frozenset[str]] = frozenset(
    {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules"}
)

#: Repository tooling scanned alongside the shipped package. Each is rglob'd
#: in full - their own test tiers (``dev/tests``, ``packaging/tests``) fall
#: out of :func:`_is_test_code` exactly like ``src``'s do.
_EXTRA_ROOTS: Final[tuple[Path, ...]] = (
    _REPO_ROOT / "dev",
    _REPO_ROOT / "packaging",
    _REPO_ROOT / "scripts",
)

#: Standalone files outside every rglob'd root.
_EXTRA_FILES: Final[tuple[Path, ...]] = (_REPO_ROOT / "conftest.py",)


def _is_test_code(relative: Path) -> bool:
    """Whether *relative* is test code or the support code tests share.

    The same rule :func:`dev.paths.is_test_code` states, restated locally.
    """
    parts = relative.parts
    if any(part in _TEST_TIERS for part in parts) or _TEST_SUPPORT in parts:
        return True
    return relative.name.startswith("test_") or relative.name == "conftest.py"


#: Below this many files visited, the scan is treated as mis-rooted rather
#: than as a tree that genuinely holds few duplicates - a floor that fails
#: LOUDLY beats a scan that silently walked the wrong directory and reported
#: a clean result for having compared nothing. Set comfortably below the
#: ~1100 modules the configured roots hold today, so routine deletions do not
#: flap it, but far above what any single misrooted root could still supply.
_VISITED_FLOOR: Final = 900

# Below this many AST nodes a shared body is more likely a coincidence of shape
# - a two-line delegating accessor, a guard-and-return - than a copied idea, and
# it is where consolidation shims live. Raising it hides real copies; lowering it
# floods the report with functions that merely rhyme.
_NODE_FLOOR: Final = 40

# Test scaffolding gets a HIGHER floor rather than exemption. This suite covered
# production only at first, on the theory that a repeated fixture is cheap. That
# was wrong in the specific way that matters: the largest duplicate group in the
# whole tree was a pair of ~138-node test fixtures, and more duplicate groups
# lived under tests/ than under production. Exempting the tier hid the majority
# of what this project actually had.
#
# The floor is higher because test code legitimately repeats more - arrange
# blocks rhyme, and two tests asserting the same refusal against different routes
# SHOULD look alike. What this catches is the other thing: a fixture that stands
# up a server, seats an environment, or drives a state machine, copied wholesale
# because finding the shared one was harder than retyping it.
_TEST_NODE_FLOOR: Final = 60

# Groups already understood. Membership is the key rather than the body hash so
# that editing an accepted duplicate does not spuriously fail this suite; what
# fails is a NEW function joining one of these shapes, or a new shape entirely.
_ACCEPTED: Final[tuple[frozenset[str], ...]] = (
    # The PEP 562 lazy-import shim. Each package's map of attribute to module
    # differs; only the lookup-and-import dance is shared. A factory generating
    # these would move the cost from three short readable functions to one
    # indirection every reader of the package has to unwind.
    frozenset(
        {
            "graph/__init__.py::__getattr__",
            "providers/__init__.py::__getattr__",
            "thread/__init__.py::__getattr__",
        }
    ),
    # Same module, differing in which debounced event kind is broadcast.
    frozenset(
        {
            "streaming/buffering.py::broadcast_debounced_plan_update",
            "streaming/buffering.py::broadcast_debounced_tool_update",
        }
    ),
)

# Reviewed groups in the TEST tier, held separately so the two floors stay
# legible. The bar for accepting one here is the same: a reason, not a recording.
_ACCEPTED_TESTS: Final[tuple[frozenset[str], ...]] = (
    # Two tests of ONE endpoint differing in whether the relay hub is the only
    # thing wired. The bodies rhyme because the arrangement does; collapsing
    # them into one parametrized case would hide which configuration failed.
    frozenset(
        {
            "api/tests/test_internal.py::test_event_with_aggregator_only_returns_ok",
            "api/tests/test_internal.py::test_valid_event_returns_ok",
        }
    ),
    # The same refusal asserted against two different route families. This is
    # the shape test code is SUPPOSED to repeat: each names the surface it
    # guards, and sharing them would leave one route's protection asserted
    # somewhere that does not mention that route.
    frozenset(
        {
            "api/tests/test_product_api_auth.py::test_product_routes_reject_unauthenticated",
            "api/tests/test_v1_attach_whitelist.py::test_whitelist_rejects_unauthenticated",
        }
    ),
    # The zombie-state poll (read the stored /proc/<pid>/stat line, compare
    # the retained inode to catch pid reuse) duplicated verbatim across the
    # in-process desktop isolation test and the frozen-binary packaging
    # artifact test. `pid_is_live`/psutil cannot stand in: neither tells
    # "pid reused" apart from "still running" inside this race window, which
    # is the one thing this poll exists to catch. The two tests deliberately
    # invoke the isolation boundary through different paths (an imported
    # module vs the packaged binary's own entry point) and the packaging
    # artifact tier does not import the unit tree whose output it verifies,
    # so sharing a helper would cross a boundary this repository keeps apart
    # on purpose. Consolidating it into a shared process-identity helper is
    # residue for that area's owner, not this guard's fix.
    frozenset(
        {
            "desktop/tests/test_native_isolation.py::_descendant_gone",
            "packaging/tests/native_isolation_artifact.py::_descendant_gone",
        }
    ),
)

# Reviewed groups that cross the production/test boundary - a shape neither of
# the two tier-scoped passes above can see, because each buckets by tier
# before it compares. Held separately a third time for the same reason: a
# group here says something different ("this test fixture and this production
# helper happen to share a shape") than a same-tier entry does.
_ACCEPTED_CROSS_TIER: Final[tuple[frozenset[str], ...]] = (
    # The PEP 562 lazy-import shim (see _ACCEPTED above), now also carried by
    # the test-support fixture-lane package. Same reason: the lookup-and-import
    # dance is shared, the attribute-to-module map is not.
    frozenset(
        {
            "graph/__init__.py::__getattr__",
            "providers/__init__.py::__getattr__",
            "testing/lanes/__init__.py::__getattr__",
            "thread/__init__.py::__getattr__",
        }
    ),
    # `testing/leases.py::_marker_is_live` mirrors `lifecycle/registry.py::
    # _reservation_is_live` by design - its own docstring says so - and the
    # bodies are now identical once names are erased: a freshness window,
    # then a missing pid treated as live, else `pid_is_live`. It stayed
    # unconsolidated because one judges production port-reservation state and
    # the other judges the pytest resource-lease marker the harness alone
    # uses; folding them into one liveness helper is residue for that area's
    # owner, not this guard's fix.
    frozenset(
        {
            "lifecycle/registry.py::_reservation_is_live",
            "testing/leases.py::_marker_is_live",
        }
    ),
)


class _EraseIdentifiers(ast.NodeTransformer):
    """Rewrite every name, argument, and attribute to one placeholder.

    What remains is the control flow and the literal structure, so two functions
    compare equal exactly when they do the same thing to differently-named
    things - which is what a copy is.
    """

    @override
    def visit_Name(self, node: ast.Name) -> ast.Name:
        """Collapse a bare name."""
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    @override
    def visit_arg(self, node: ast.arg) -> ast.arg:
        """Collapse a parameter, annotation included."""
        return ast.copy_location(ast.arg(arg="_", annotation=None), node)

    @override
    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        """Collapse an attribute access, keeping the value it reaches through."""
        self.generic_visit(node)
        return ast.copy_location(
            ast.Attribute(value=node.value, attr="_", ctx=node.ctx), node
        )


@dataclass(frozen=True)
class _Function:
    """One hashed function body, wherever it was found."""

    qualified_name: str
    shape: str
    node_count: int
    is_test: bool


def _structure_hash(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, int] | None:
    """Hash *function*'s body shape, or None when it has no body to hash.

    The node count is returned rather than compared here: the floor a function
    must clear differs by tier and by pass, while the hash itself does not, so
    computing it once and filtering per-pass avoids hashing the same body twice
    under two different floors.
    """
    body = [
        statement
        for statement in function.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]
    if not body:
        return None
    module = ast.Module(body=body, type_ignores=[])
    node_count = sum(1 for _ in ast.walk(module))
    erased = _EraseIdentifiers().visit(module)
    ast.fix_missing_locations(erased)
    digest = hashlib.sha256(ast.dump(erased).encode()).hexdigest()
    return digest, node_count


def _relative(path: Path) -> Path:
    """Render *path* relative to whichever configured root contains it.

    The shipped package is tried first so its members keep the short,
    already-reviewed key form (``"graph/__init__.py::__getattr__"``); every
    other configured root falls back to the repository root, which cannot
    collide with a package-relative key because none of ``dev/``,
    ``packaging/``, ``scripts/`` or ``conftest.py`` names a top-level member
    of ``src/vaultspec_a2a``.
    """
    for root in (_SOURCE_ROOT, _REPO_ROOT):
        try:
            return path.relative_to(root)
        except ValueError:
            continue
    raise ValueError(f"{path} is outside every configured root")  # pragma: no cover


def _discovered_files() -> list[Path]:
    """Return every module the scan covers, across every configured root."""
    found = [
        path
        for root in (_SOURCE_ROOT, *_EXTRA_ROOTS)
        for path in root.rglob("*.py")
        if not any(part in _SKIPPED_DIRS for part in path.parts)
    ]
    found.extend(path for path in _EXTRA_FILES if path.is_file())
    return sorted(found)


@lru_cache(maxsize=1)
def _catalog() -> tuple[_Function, ...]:
    """Hash every function in every configured root, once.

    Raises when a root is mis-configured rather than letting a scan that
    covered nothing report a clean result: a module that fails to parse is a
    repository defect, not a file to skip, and a root or standalone file that
    contributed zero paths is this test pointing at the wrong tree.
    """
    for root in (_SOURCE_ROOT, *_EXTRA_ROOTS):
        assert root.is_dir() and any(root.rglob("*.py")), (
            f"{root} contributed no Python files - a mis-rooted scan, not an empty tree"
        )
    for path in _EXTRA_FILES:
        assert path.is_file(), f"{path} is missing - a mis-rooted scan"

    functions: list[_Function] = []
    visited = 0
    for path in _discovered_files():
        relative = _relative(path)
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=relative.as_posix())
        except SyntaxError as exc:
            raise AssertionError(f"{relative}: could not parse: {exc}") from exc
        visited += 1
        is_test = _is_test_code(relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                hashed = _structure_hash(node)
                if hashed is not None:
                    shape, node_count = hashed
                    functions.append(
                        _Function(
                            f"{relative.as_posix()}::{node.name}",
                            shape,
                            node_count,
                            is_test,
                        )
                    )

    assert visited >= _VISITED_FLOOR, (
        f"only {visited} files were scanned (floor {_VISITED_FLOOR}) - a "
        "mis-rooted scan must not pass vacuously"
    )
    return tuple(functions)


def _groups(
    functions: tuple[_Function, ...], *, floor: int, tier: bool
) -> list[set[str]]:
    """Return every set of same-tier functions sharing one body shape."""
    by_shape: dict[str, set[str]] = defaultdict(set)
    for function in functions:
        if function.is_test is tier and function.node_count >= floor:
            by_shape[function.shape].add(function.qualified_name)
    return [members for members in by_shape.values() if len(members) > 1]


def _cross_tier_groups(
    functions: tuple[_Function, ...], *, floor: int
) -> list[set[str]]:
    """Return shape-identical groups whose members span BOTH tiers.

    :func:`_groups` buckets by tier before it compares shapes, so neither
    tier-scoped test sees a production function cloned into test scaffolding,
    or a test fixture copied into production: they never land in the same
    bucket. This pass drops the tier split and keeps only the groups that
    actually straddle it.
    """
    by_shape: dict[str, set[str]] = defaultdict(set)
    tiers_seen: dict[str, set[bool]] = defaultdict(set)
    for function in functions:
        if function.node_count < floor:
            continue
        by_shape[function.shape].add(function.qualified_name)
        tiers_seen[function.shape].add(function.is_test)
    return [
        members
        for shape, members in by_shape.items()
        if len(members) > 1 and len(tiers_seen[shape]) > 1
    ]


def _assert_reviewed(
    groups: list[set[str]], accepted: tuple[frozenset[str], ...], allowlist: str
) -> None:
    """Fail naming any group that is not a subset of a reviewed one."""
    unreviewed = [
        group for group in groups if not any(group <= entry for entry in accepted)
    ]
    assert not unreviewed, (
        "These functions have identical bodies once every identifier is erased, "
        "so they implement the same thing under different names:\n\n"
        + "\n\n".join(
            "  " + "\n  ".join(sorted(group))
            for group in sorted(unreviewed, key=sorted)
        )
        + "\n\nConsume the existing one instead of keeping the copy. If they are "
        "genuinely distinct - the same shape applied to different tables, "
        f"columns, or event kinds is a real case - add the group to {allowlist} "
        "with a sentence saying why, so the judgement is visible to whoever "
        "reads this next."
    )


def test_no_unreviewed_structural_duplicate() -> None:
    """Every set of identically-shaped production functions must be reviewed."""
    _assert_reviewed(
        _groups(_catalog(), floor=_NODE_FLOOR, tier=False), _ACCEPTED, "_ACCEPTED"
    )


def test_no_unreviewed_structural_duplicate_in_tests() -> None:
    """Substantial test scaffolding must not be copied either.

    Separate from the production case because the floor differs and because a
    failure here has a different remedy: shared test mechanism belongs in
    ``testing/``, not in whichever test module happened to need it first.
    """
    _assert_reviewed(
        _groups(_catalog(), floor=_TEST_NODE_FLOOR, tier=True),
        _ACCEPTED_TESTS,
        "_ACCEPTED_TESTS",
    )


def test_no_unreviewed_structural_duplicate_across_tiers() -> None:
    """Substantial clones that cross the production/test boundary.

    A production helper hashed identically to a test fixture is invisible to
    the two tests above by construction - see :func:`_cross_tier_groups`. The
    production floor applies here because a group spanning both tiers is, by
    definition, at least as substantial as the smaller side already requires.
    """
    _assert_reviewed(
        _cross_tier_groups(_catalog(), floor=_NODE_FLOOR),
        _ACCEPTED_CROSS_TIER,
        "_ACCEPTED_CROSS_TIER",
    )
