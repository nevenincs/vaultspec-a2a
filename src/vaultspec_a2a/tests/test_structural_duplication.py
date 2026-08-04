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
from pathlib import Path
from typing import Final

_SOURCE_ROOT = Path(__file__).resolve().parents[1]

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
    # Same repository, differing only in the column grouped by. Two named
    # queries say which aggregate is being asked for at the call site; one
    # parametrized query moves that into an argument the reader must resolve.
    frozenset(
        {
            "database/artifact_repository.py::sum_cost_by_agent",
            "database/artifact_repository.py::sum_cost_by_thread",
        }
    ),
    # Same repository, different tables and different row models. The shape is
    # shared because the access pattern is, not because the query is.
    frozenset(
        {
            "database/artifact_repository.py::get_artifacts_by_thread",
            "database/artifact_repository.py::get_permission_logs_by_thread",
        }
    ),
    # Same repository, two lookup keys onto one table. Merging them would take
    # the key as a column name, which is how a typo becomes a runtime error
    # instead of a name error.
    frozenset(
        {
            "database/permission_repository.py::get_control_action_by_dispatch_id",
            "database/permission_repository.py::get_control_action_by_idempotency_key",
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
    # QUEUED, not endorsed. Investigated during the sweep and found safe to
    # share - both build against an unreachable bridge and an in-memory
    # checkpointer, so the live file's live-ness is not in this helper - but it
    # spans two packages and was deferred rather than done.
    frozenset(
        {
            "control/tests/test_verdict_subscriber.py::_install_receipt_graph",
            "control/tests/test_verdict_subscriber_live.py::_install_receipt_graph",
        }
    ),
    # Two tests of ONE endpoint differing in whether the aggregator is the only
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
)


class _EraseIdentifiers(ast.NodeTransformer):
    """Rewrite every name, argument, and attribute to one placeholder.

    What remains is the control flow and the literal structure, so two functions
    compare equal exactly when they do the same thing to differently-named
    things - which is what a copy is.
    """

    def visit_Name(self, node: ast.Name) -> ast.Name:
        """Collapse a bare name."""
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg) -> ast.arg:
        """Collapse a parameter, annotation included."""
        return ast.copy_location(ast.arg(arg="_", annotation=None), node)

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        """Collapse an attribute access, keeping the value it reaches through."""
        self.generic_visit(node)
        return ast.copy_location(
            ast.Attribute(value=node.value, attr="_", ctx=node.ctx), node
        )


def _structure_hash(
    function: ast.FunctionDef | ast.AsyncFunctionDef, floor: int
) -> str | None:
    """Hash *function*'s body shape, or None when it is below *floor*."""
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
    if sum(1 for _ in ast.walk(module)) < floor:
        return None
    erased = _EraseIdentifiers().visit(module)
    ast.fix_missing_locations(erased)
    return hashlib.sha256(ast.dump(erased).encode()).hexdigest()


def _is_test_module(path: Path) -> bool:
    """Report whether *path* is test code rather than production code."""
    parts = path.parts
    return "tests" in parts or "testing" in parts or path.name.startswith("test_")


def _structural_groups(*, tests: bool, floor: int) -> list[set[str]]:
    """Return every set of same-tier functions sharing one body shape."""
    by_shape: dict[str, set[str]] = defaultdict(set)
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(_SOURCE_ROOT)
        if _is_test_module(relative) is not tests:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                shape = _structure_hash(node, floor)
                if shape is not None:
                    by_shape[shape].add(f"{relative.as_posix()}::{node.name}")
    return [members for members in by_shape.values() if len(members) > 1]


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
        _structural_groups(tests=False, floor=_NODE_FLOOR), _ACCEPTED, "_ACCEPTED"
    )


def test_no_unreviewed_structural_duplicate_in_tests() -> None:
    """Substantial test scaffolding must not be copied either.

    Separate from the production case because the floor differs and because a
    failure here has a different remedy: shared test mechanism belongs in
    ``testing/``, not in whichever test module happened to need it first.
    """
    _assert_reviewed(
        _structural_groups(tests=True, floor=_TEST_NODE_FLOOR),
        _ACCEPTED_TESTS,
        "_ACCEPTED_TESTS",
    )
