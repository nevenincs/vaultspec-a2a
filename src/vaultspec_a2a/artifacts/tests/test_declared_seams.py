"""Every declaring module must be enumerable, and every declaration usable.

A declaration nobody can find is worth as much as no declaration at all, so this
suite imports the real modules that declare artifacts and asserts their
collections hold together: names unique across the service, roots expressed as
path expressions rather than resolved paths, and a mechanism that says something
an operator could act on.

The list of declaring modules is maintained by hand on purpose.  Discovering it
by walking the package would make the suite pass automatically for a module that
declares nothing, which is the exact failure it exists to catch.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

from ...cli import provision
from ...control import worker_management
from ...database import admin, checkpoints, reconciliation, session
from ...desktop import credentials, profile
from ...lifecycle import discovery, manager, registry, singleton
from ...protocols.mcp import authoring_stdio
from ...providers import (
    _acp_rpc_handlers,
    _codex_config_home,
    _config_home_roots,
    acp_chat_model,
)
from ...service_tests import harness
from ...testing import leases
from ...utils import logging as utils_logging
from ..retention import ArtifactDeclaration, RetentionDisposition

if TYPE_CHECKING:
    from types import ModuleType

_DECLARING_MODULES: tuple[ModuleType, ...] = (
    discovery,
    worker_management,
    provision,
    admin,
    checkpoints,
    reconciliation,
    session,
    credentials,
    manager,
    registry,
    singleton,
    _acp_rpc_handlers,
    _codex_config_home,
    _config_home_roots,
    acp_chat_model,
    harness,
    utils_logging,
    profile,
    authoring_stdio,
    leases,
)

_INVENTORY_NAME = "ARTIFACT_DECLARATIONS"
_DECLARATION_SUFFIX = "_DECLARATION"
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _all_declarations() -> list[ArtifactDeclaration]:
    """Collect every declaration the declaring modules expose."""
    collected: list[ArtifactDeclaration] = []
    for module in _DECLARING_MODULES:
        collected.extend(module.ARTIFACT_DECLARATIONS)
    return collected


def test_every_declaring_module_exposes_a_non_empty_collection() -> None:
    """A module in the list that declares nothing is a regression, not a pass."""
    for module in _DECLARING_MODULES:
        declarations = module.ARTIFACT_DECLARATIONS

        assert isinstance(declarations, tuple), module.__name__
        assert declarations, f"{module.__name__} declares no artifacts"


def test_artifact_names_are_unique_across_the_service() -> None:
    """Two seams sharing a name make the inventory ambiguous."""
    names = [declaration.name for declaration in _all_declarations()]

    assert len(names) == len(set(names)), f"duplicate artifact names: {names}"


def test_roots_are_path_expressions_not_resolved_paths() -> None:
    """A resolved path would bake in one host and go stale under a reseated home."""
    for declaration in _all_declarations():
        root = declaration.root

        assert "<" in root and ">" in root, (
            f"{declaration.name!r} root {root!r} looks resolved; declare it as a "
            "path expression so it stays true across hosts and profiles"
        )
        assert not root.startswith(("/", "C:", "c:")), (
            f"{declaration.name!r} root {root!r} is an absolute path"
        )


def test_every_declaration_names_an_owner_and_a_mechanism() -> None:
    """The two facts a reader needs to act: who is responsible, and what enforces it."""
    for declaration in _all_declarations():
        assert declaration.owner.strip(), declaration.name
        assert declaration.mechanism.strip(), declaration.name


def test_a_permanent_declaration_carries_its_justification() -> None:
    """Permanence is allowed anywhere in the service, but never unexplained."""
    for declaration in _all_declarations():
        if declaration.disposition is RetentionDisposition.PERMANENT:
            assert declaration.reason, (
                f"{declaration.name!r} is permanent without a reason"
            )


def _modules_assigning_an_inventory() -> dict[str, set[str]]:
    """Map each source module that assigns the inventory to its top-level names.

    Read by parsing sources rather than by importing the package.  The hand list
    above stays the authority on WHAT is checked; this only establishes what
    exists, so a module can never be checked into invisibility.
    """
    found: dict[str, set[str]] = {}
    for source in sorted(_PACKAGE_ROOT.rglob("*.py")):
        relative = source.relative_to(_PACKAGE_ROOT)
        if "tests" in relative.parts:
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        names: set[str] = set()
        for node in tree.body:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            names.update(t.id for t in targets if isinstance(t, ast.Name))
        if _INVENTORY_NAME in names:
            found[str(relative.with_suffix("")).replace("\\", "/")] = names
    return found


def test_the_hand_maintained_list_omits_no_declaring_module() -> None:
    """A new declaring module must be registered above, not silently unchecked.

    The list is hand-maintained deliberately: walking the package to BUILD it
    would let a module that declares nothing pass by default.  That reasoning
    argues against deriving the list, not against verifying it is complete - and
    without this check the failure mode is the quiet one, where a seam is
    declared, never registered, and covered by none of the assertions here.
    """
    registered = {
        module.__name__.removeprefix("vaultspec_a2a.").replace(".", "/")
        for module in _DECLARING_MODULES
    }
    on_disk = set(_modules_assigning_an_inventory())

    assert on_disk, "no module assigning the inventory was found; the parse is broken"
    assert on_disk <= registered, (
        f"these modules declare artifacts but are absent from _DECLARING_MODULES: "
        f"{sorted(on_disk - registered)}"
    )


def test_every_declaration_names_the_module_it_lives_in() -> None:
    """``owner`` must be the declaring module, which is what makes drift visible.

    A declaration sits beside its creating call site so it cannot describe a seam
    somewhere else.  An ``owner`` that has stopped matching its own module is
    exactly that drift, and no per-declaration validation can see it.
    """
    mismatched = [
        (module.__name__, declaration.name, declaration.owner)
        for module in _DECLARING_MODULES
        for declaration in module.ARTIFACT_DECLARATIONS
        if module.__name__ != f"vaultspec_a2a.{declaration.owner}"
    ]

    assert not mismatched, (
        f"these declarations name an owner that is not their own module: {mismatched}"
    )


def test_no_declaration_constant_is_left_out_of_its_module_inventory() -> None:
    """A constant absent from the tuple is enumerable by nothing.

    The tuple is how a reviewer, and eventually a reaper, finds what a module
    creates.  A ``*_DECLARATION`` that exists but is unlisted reads as coverage
    and provides none.
    """
    on_disk = _modules_assigning_an_inventory()
    omitted: list[tuple[str, str]] = []
    for module in _DECLARING_MODULES:
        key = module.__name__.removeprefix("vaultspec_a2a.").replace(".", "/")
        names = on_disk.get(key, set())
        constants = {
            name
            for name in names
            if name.endswith(_DECLARATION_SUFFIX)
            and isinstance(getattr(module, name, None), ArtifactDeclaration)
        }
        assert constants, f"{module.__name__} exposes no declaration constant"
        omitted.extend(
            (module.__name__, name)
            for name in constants
            if getattr(module, name) not in module.ARTIFACT_DECLARATIONS
        )

    assert not omitted, (
        f"these declarations are defined but missing from {_INVENTORY_NAME}: {omitted}"
    )


def _production_sources() -> list[Path]:
    """Every package source that is product code rather than test code."""
    return [
        source
        for source in sorted(_PACKAGE_ROOT.rglob("*.py"))
        if "tests" not in source.relative_to(_PACKAGE_ROOT).parts
    ]


def test_no_production_caller_asks_the_acp_lane_to_resume_a_persisted_session() -> None:
    """The transcript declaration rests on this lane never reading one back.

    ``session/load`` is wired and fires only when a construction supplies
    ``session_id``.  No production one does, which is what makes the CLI's own
    transcript pure residue here - and what makes suppressing the write upstream
    a free change rather than the loss of a capability.  Wiring a production
    resume would falsify both claims silently, so it fails here instead.
    """
    resuming: list[str] = []
    for source in _production_sources():
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id == "AcpChatModel"):
                continue
            if any(keyword.arg == "session_id" for keyword in node.keywords):
                relative = source.relative_to(_PACKAGE_ROOT)
                resuming.append(f"{relative.as_posix()}:{node.lineno}")

    assert not resuming, (
        "these production call sites resume a persisted provider session, which "
        f"contradicts {acp_chat_model.ACP_SESSION_TRANSCRIPT_DECLARATION.name!r}: "
        f"{resuming}"
    )


def test_the_acp_lane_takes_no_deletion_authority_over_the_operator_home() -> None:
    """The seam that declares the transcript must never learn to reclaim it.

    The declaration's whole argument is that no predicate available here can
    separate a session a run spawned from one the operator started by hand, so
    the correct remedy is upstream suppression and the correct local behaviour is
    to touch nothing.  A removal call appearing in this module would be that
    argument being quietly abandoned.
    """
    source = _PACKAGE_ROOT / "providers" / "acp_chat_model.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    removers = {"rmtree", "unlink", "remove", "rmdir", "removedirs"}

    found = [
        f"{node.func.attr} at line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in removers
    ]

    assert not found, (
        f"{source.name} acquired filesystem deletion authority: {found}. The ACP "
        "lane runs in the operator's real config home; nothing here may delete "
        "from it"
    )


def test_the_acp_transcript_declares_an_enforcer_it_does_not_own() -> None:
    """Its bound is real but external, and the declaration must say whose it is."""
    declaration = acp_chat_model.ACP_SESSION_TRANSCRIPT_DECLARATION

    assert declaration.disposition is RetentionDisposition.BOUNDED_BY_AGE
    assert "cleanupPeriodDays" in declaration.mechanism
    assert "operator" in declaration.mechanism.lower()


def test_the_discovery_record_declares_its_crash_exposure() -> None:
    """The stale-record gap must stay visible until a Step closes it.

    A mechanism that claimed clean removal would misrepresent the artifact whose
    survival past its own process was read as a live unauthenticated gateway.
    """
    declaration = discovery.SERVICE_DISCOVERY_DECLARATION

    assert declaration.disposition is RetentionDisposition.SESSION_SCOPED
    assert "crash" in declaration.mechanism.lower()
