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

from vaultspec_a2a.control import worker_management
from vaultspec_a2a.lifecycle import discovery

from ..retention import ArtifactDeclaration, RetentionDisposition

_DECLARING_MODULES = (discovery, worker_management)


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


def test_the_discovery_record_declares_its_crash_exposure() -> None:
    """The stale-record gap must stay visible until a Step closes it.

    A mechanism that claimed clean removal would misrepresent the artifact whose
    survival past its own process was read as a live unauthenticated gateway.
    """
    declaration = discovery.SERVICE_DISCOVERY_DECLARATION

    assert declaration.disposition is RetentionDisposition.SESSION_SCOPED
    assert "crash" in declaration.mechanism.lower()
