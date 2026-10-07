"""The one project a run's tool calls may address, and the scans that enforce it.

A run is admitted against one project, and every lane's tools take that project
as an argument rather than inheriting it, so the escape is argument-borne and the
check has to run where calls pass. That place is the permission decision both
lanes share, ``_tool_policy.decide``, which runs the foreign-project scan here
ahead of either lane's rung, so the two cannot come to disagree about what
"another project" means.

A tool that takes no project still takes a PATH, and a path reaches just as far:
the lanes' own read built-ins read whatever file they are handed, so the second
scan here measures a call's path arguments against the same bound project; the
ACP permission handler applies it to a native read call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

from ..control.workspace import canonical_workspace_root

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from ._json_contract import JsonObject, JsonValue

__all__ = [
    "RunProjectScope",
    "foreign_project_argument",
    "path_arguments_in_project",
]


def _project_scope_key(value: str | os.PathLike[str]) -> str:
    """Return one project path in the single form scope decisions compare.

    The active project reaches a scope decision in several spellings - the
    engine's wire form, the run's stored path, a search service's per-call root,
    a command-line target - and a comparison between two of them is a
    comparison between two conventions. Every value is therefore reduced to the
    workspace boundary's own authority form, so the permission layer and
    admission cannot disagree about what one spelling names, and is then
    case-normalised the way the platform's own path convention is: folded on
    Windows, unchanged elsewhere, where folding would merge distinct directories.

    Raises:
        ValueError: If *value* is blank, relative or home-relative, or does not
            reduce to an absolute path. Each would be measured against this
            process's working directory or home rather than the agent's.
        OSError: If the OS refuses to resolve *value*.
    """
    return os.path.normcase(str(canonical_workspace_root(value)))


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

# Tool-call argument keys that name a filesystem path to work on. The read
# built-ins of both lanes take their target this way, and the ACP tool-call
# payload repeats it under ``locations`` as the adapter's own statement of which
# files a call touches, keyed the same.
#
# A SEARCH PATTERN IS NOT LISTED, and the omission is the decision: ``pattern``
# is a path glob on one built-in and a regular expression on its neighbour, so
# reading it as a path by key would refuse a legitimate search for a literal
# path. A pattern that actually reaches out of the project is caught by
# :func:`_reaches_past_its_own_directory` instead, which asks about the VALUE.
_PATH_ARGUMENT_KEYS: frozenset[str] = frozenset(
    {"path", "paths", "file_path", "filePath", "notebook_path", "notebookPath"}
)


class RunProjectScope:
    """One run's project scope: what every lane measures a tool call against."""

    __slots__ = ("_workspace_root",)

    def __init__(self, workspace_root: str | None) -> None:
        self._workspace_root = workspace_root

    def bound_project_root(self) -> str | None:
        """Return the project this run is bound to, or ``None`` if it has none.

        ``workspace_root`` is the active project the run was created with. This
        reader is what makes it usable as an AUTHORITY rather than only as a
        starting directory: it hands back the scope key, so a caller comparing
        against it cannot accidentally compare spellings.

        ``None`` is not "unrestricted". It means the run carries no project, or
        one that does not reduce to a key, so a caller deciding whether to
        permit something must read it as "no authority to permit against" - see
        :meth:`binds_project_path`.
        """
        if not self._workspace_root:
            return None
        try:
            return _project_scope_key(self._workspace_root)
        except (OSError, ValueError):
            return None

    def binds_project_path(self, candidate: str | Path) -> bool:
        """Return whether *candidate* lies inside the project the run is bound to.

        Containment rather than equality, because a path UNDER the run's project
        is still the run's project: refusing a subdirectory would refuse
        legitimately scoped work while closing nothing. A parent of the bound
        project is NOT contained - widening the scope upward is exactly the
        escape this answers.

        Returns ``False`` when the run carries no project and for a candidate
        that does not reduce to a key: a comparison that cannot be made is not a
        comparison that passed.
        """
        bound = self.bound_project_root()
        if bound is None:
            return False
        try:
            key = _project_scope_key(candidate)
        except (OSError, ValueError):
            return False
        # Both sides are reduced to the scope key, so this is a pure lexical
        # containment test - no second normalisation convention can creep in.
        return Path(key).is_relative_to(Path(bound))


def _foreign_project_field(key: str, value: JsonValue, scope: RunProjectScope) -> bool:
    return (
        key in _PROJECT_ARGUMENT_KEYS
        and isinstance(value, str)
        and bool(value.strip())
        and not scope.binds_project_path(value.strip())
    )


def _scan_foreign_project_mapping(
    value: JsonObject, scope: RunProjectScope, depth: int
) -> str | None:
    for key, item in value.items():
        if _foreign_project_field(key, item, scope):
            return str(item)
        found = _scan_foreign_project_argument(item, scope, depth + 1)
        if found is not None:
            return found
    return None


def _scan_foreign_project_argument(
    value: JsonValue, scope: RunProjectScope, depth: int
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


def foreign_project_argument(args: JsonObject, scope: RunProjectScope) -> str | None:
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


@dataclass(frozen=True, slots=True)
class _PathArgumentScan:
    """Where a tool call said it would work, measured against the run's project."""

    inside: tuple[str, ...]
    outside: tuple[str, ...]

    @property
    def confined(self) -> bool:
        """Whether the call named a path and every path it named is the run's.

        Naming nothing is not confinement. A call that writes down no path at
        all is bounded by whatever directory the tool happens to run in, which
        is a property of the spawned process rather than a statement the caller
        made, so there is nothing here to compare against the bound project.
        """
        return bool(self.inside) and not self.outside


def _string_fields(value: JsonValue, key: str, depth: int) -> Iterator[tuple[str, str]]:
    """Yield every string in an untrusted payload beside the key that held it.

    A list inherits its parent's key, because the key is what says a value names
    a path and a list of paths is spelled under one.
    """
    if depth > _MAX_ARGUMENT_SCAN_DEPTH:
        return
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for child_key, child in value.items():
            yield from _string_fields(child, child_key, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _string_fields(item, key, depth + 1)


def _reaches_past_its_own_directory(value: str) -> bool:
    """Whether a string could address a file outside the directory it runs in.

    Asked of the value rather than its key, because a key can be spelled any way
    a CLI likes and an unlisted one would otherwise pass unread. Only two shapes
    leave the directory a call runs in - an absolute or home-relative path, and
    one that steps upward - so these are read as paths whatever they are called,
    while an ordinary relative string is read as a path only where its key says
    it is one.
    """
    return (
        value.startswith("~")
        or PurePath(value).is_absolute()
        or ".." in PurePath(value).parts
    )


def _anchored_to(value: str, bound: str) -> str:
    """Return *value* as a path to compare, anchoring a relative one to *bound*.

    A relative argument is resolved by the spawned CLI against its own working
    directory, which is the run's project, so anchoring it anywhere else - the
    serving process's directory, say - would compare a path the call never
    meant.
    """
    if value.startswith("~") or PurePath(value).is_absolute():
        return value
    return str(PurePath(bound) / value)


def path_arguments_in_project(
    args: JsonObject, locations: Sequence[JsonObject], scope: RunProjectScope
) -> _PathArgumentScan:
    """Measure a tool call's path arguments against the project the run is bound to.

    Both halves of the ACP tool-call payload are read: ``rawInput``, which is
    what the model asked for, and ``locations``, which is the adapter's own
    account of the files the call touches. Neither is trusted over the other and
    a path from either must be the run's.

    A run with no bound project has no authority to compare against, so every
    named path is reported outside - the same reading :meth:`binds_project_path`
    gives a comparison that cannot be made.
    """
    bound = scope.bound_project_root()
    inside: list[str] = []
    outside: list[str] = []
    fields = list(_string_fields(args, "", 0))
    for location in locations:
        fields.extend(_string_fields(location, "", 0))
    for key, raw in fields:
        value = raw.strip()
        if not value:
            continue
        if key not in _PATH_ARGUMENT_KEYS and not _reaches_past_its_own_directory(
            value
        ):
            continue
        if bound is not None and scope.binds_project_path(_anchored_to(value, bound)):
            inside.append(value)
        else:
            outside.append(value)
    return _PathArgumentScan(tuple(inside), tuple(outside))
