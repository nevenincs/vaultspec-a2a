"""The one project a run's tool calls may address, and the scan that enforces it.

A run is admitted against one project, and every lane's tools take that project
as an argument rather than inheriting it, so the escape is argument-borne and the
check has to run where calls pass. Both lanes have such a place - the ACP
permission handler and the Codex approval rung - and this is the single scan they
share, so the two cannot come to disagree about what "another project" means.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ._acp_types import canonical_project_root

if TYPE_CHECKING:
    from ._json_contract import JsonObject, JsonValue

__all__ = ["ProjectScope", "RunProjectScope", "foreign_project_argument"]


class ProjectScope(Protocol):
    """What a permission decision needs to know about a run's project."""

    def bound_project_root(self) -> str | None:
        """Return the project this run is bound to, or ``None`` if it has none."""
        ...

    def binds_project_path(self, candidate: str | Path) -> bool:
        """Return whether *candidate* lies inside the run's own project."""
        ...


# Tool-call argument keys that name a project to operate on. The search tools a
# run is handed take their root this way - ``project_root`` on every
# vaultspec-rag tool - which is how a scope escape arrives as an ARGUMENT that no
# per-server trust assertion can express. Both the snake_case and camelCase
# spellings are listed because the argument crosses a JSON boundary where either
# convention is admissible.
_PROJECT_ARGUMENT_KEYS: frozenset[str] = frozenset(
    {"project_root", "projectRoot", "workspace_root", "workspaceRoot"}
)

# Depth bound for the argument scan. Tool inputs are flat in practice (the search
# adapter exposes a deliberately flat schema), so this exists only so untrusted,
# deeply nested input cannot turn a permission decision into a recursion.
_MAX_ARGUMENT_SCAN_DEPTH = 6


class RunProjectScope:
    """One run's project scope, for a lane that carries no ACP model config."""

    __slots__ = ("_workspace_root",)

    def __init__(self, workspace_root: str | None) -> None:
        self._workspace_root = workspace_root

    def bound_project_root(self) -> str | None:
        """Return the canonical project this run is bound to."""
        if not self._workspace_root:
            return None
        return canonical_project_root(self._workspace_root)

    def binds_project_path(self, candidate: str | Path) -> bool:
        """Return whether *candidate* lies inside the project the run is bound to."""
        bound = self.bound_project_root()
        if bound is None:
            return False
        return Path(canonical_project_root(candidate)).is_relative_to(Path(bound))


def _foreign_project_field(key: str, value: JsonValue, scope: ProjectScope) -> bool:
    return (
        key in _PROJECT_ARGUMENT_KEYS
        and isinstance(value, str)
        and bool(value.strip())
        and not scope.binds_project_path(value.strip())
    )


def _scan_foreign_project_mapping(
    value: JsonObject, scope: ProjectScope, depth: int
) -> str | None:
    for key, item in value.items():
        if _foreign_project_field(key, item, scope):
            return str(item)
        found = _scan_foreign_project_argument(item, scope, depth + 1)
        if found is not None:
            return found
    return None


def _scan_foreign_project_argument(
    value: JsonValue, scope: ProjectScope, depth: int
) -> str | None:
    if depth > _MAX_ARGUMENT_SCAN_DEPTH:
        return None
    if isinstance(value, dict):
        return _scan_foreign_project_mapping(value, scope, depth)
    if isinstance(value, list):
        for item in value:
            if (
                found := _scan_foreign_project_argument(item, scope, depth + 1)
            ) is not None:
                return found
    return None


def foreign_project_argument(args: JsonObject, scope: ProjectScope) -> str | None:
    """Return the first argument naming a project outside the run's, or ``None``.

    The escape this closes is argument-borne: the run's grounding tools resolve a
    caller-supplied root against any enrolled workspace on the machine, so a call
    the registry considers entirely read-only and entirely local still returns
    another project's content. The trust boundary is therefore the call, and both
    lanes run this where their calls pass.

    A named project that is not the run's is REPORTED, not corrected. Rewriting
    the argument to the bound project would answer a different question than the
    agent asked and hide that it asked it.
    """
    return _scan_foreign_project_argument(args, scope, 0)
