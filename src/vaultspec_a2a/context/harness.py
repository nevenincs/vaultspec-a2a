"""Agent harness verification (agent-harness-provisioning ADR).

An authoring run's agent harness is a set of workspace surfaces the runtime
needs present and readable before dispatch: rules, templates, skills, and the
vaultspec-core CLI (the read-only self-validation tool). Four of these degraded
SILENTLY - an unprovisioned workspace produced agents that authored blind with
no error anywhere - and one (skills) had no runtime concept at all (research).
This module turns harness completeness into a VERIFIED verdict with safe
reasons, so the shared eligibility service can serve it at discovery and refuse
on it at run-start instead of hoping.

The verifier is read-only and workspace-scoped: it inspects the flat
``.vaultspec/`` corpus a provisioned workspace carries and checks the
``vaultspec-core`` CLI resolves in the agent's environment. It never writes,
never spawns the CLI, and never emits a filesystem path in a served reason -
reasons name WHAT is missing, not WHERE.

References:
    - agent-harness-provisioning ADR (the harness contract; the
      ``Verification, not hope`` clause)
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .rules import DEFAULT_BUNDLED_RULES_DIR, RuleManager

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "DEFAULT_REQUIRED_TEMPLATES",
    "HarnessReadiness",
    "verify_harness",
]

# The flat ``.vaultspec/`` corpus subdirectories a provisioned workspace carries
# under the current vaultspec-core schema.
_TEMPLATES_DIR = Path(".vaultspec") / "templates"
_SKILLS_DIR = Path(".vaultspec") / "skills"

# The canonical authoring templates every placeholder is filled from. A
# document-authoring harness requires these readable on disk - the first S10 run
# shipped an ADR carrying the raw ``{accepted|rejected|...}`` enum precisely
# because none were reachable (research).
DEFAULT_REQUIRED_TEMPLATES: tuple[str, ...] = (
    "adr",
    "plan",
    "research",
    "reference",
    "exec-step",
    "exec-summary",
)

# The CLI the agent environment must resolve for read-only self-validation
# (template reading, ``vault check`` on drafts staged outside ``.vault/``): the
# console script on PATH, or the ``uvx`` shim that runs
# ``uvx --from vaultspec-core vaultspec-core`` (the ws5 provisioning recipe).
_CLI_NAMES: tuple[str, ...] = ("vaultspec-core", "uvx")


@dataclass(frozen=True, slots=True)
class HarnessReadiness:
    """Whether an authoring workspace's agent harness is complete and readable.

    ``ready`` is True only when every checked surface is present; ``reasons``
    lists each missing surface with a safe, path-free human string. A not-ready
    verdict is an eligibility signal, never a raise - the caller composes it into
    the served eligibility. Never carries a filesystem path or secret.
    """

    ready: bool
    reasons: list[str] = field(default_factory=list)


def verify_harness(
    workspace_root: Path,
    *,
    required_skills: Sequence[str] = (),
    required_templates: Sequence[str] = DEFAULT_REQUIRED_TEMPLATES,
) -> HarnessReadiness:
    """Verify an authoring workspace carries a complete agent harness.

    Checks, each contributing one safe reason on failure:

    - **rules**: the ``RuleManager`` resolves rule content for the run - the
      union of the workspace ``.vaultspec/rules`` corpus and the bundled
      in-process defaults, so a bundled-only (Path B) workspace is satisfied
      even with no ``.vaultspec/rules`` on disk;
    - **templates**: every name in *required_templates* is present as
      ``.vaultspec/templates/<name>.md``;
    - **skills**: every name in *required_skills* is present under
      ``.vaultspec/skills/`` (a ``<name>/SKILL.md`` skill directory or a
      ``<name>.md`` file);
    - **tools**: the ``vaultspec-core`` CLI resolves in the agent environment.

    *required_skills* is the declared harness's skills list (empty by default -
    the ``[team.harness]`` schema supplies it); a run that declares no skills is
    not failed on the skills surface. Read-only: no write, no CLI spawn.
    """
    root = workspace_root.resolve()
    reasons: list[str] = []

    if not _rule_content_resolves(root):
        reasons.append(
            "no rule content resolvable for the run "
            "(neither the workspace corpus nor the bundled defaults)"
        )

    templates_dir = root / _TEMPLATES_DIR
    missing_templates = sorted(
        name
        for name in required_templates
        if not (templates_dir / f"{name}.md").is_file()
    )
    if missing_templates:
        reasons.append("required templates missing: " + ", ".join(missing_templates))

    skills_dir = root / _SKILLS_DIR
    missing_skills = sorted(
        name for name in required_skills if not _skill_present(skills_dir, name)
    )
    if missing_skills:
        reasons.append("declared skills missing: " + ", ".join(missing_skills))

    if not _cli_resolvable():
        reasons.append("vaultspec-core CLI does not resolve in the agent environment")

    return HarnessReadiness(ready=not reasons, reasons=reasons)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _rule_content_resolves(root: Path) -> bool:
    """True when the ``RuleManager`` resolves any rule content for *root*.

    Rules are delivered in-process by the ``RuleManager`` as the union of the
    workspace ``.vaultspec/rules`` corpus and the bundled defaults
    (:data:`~vaultspec_a2a.context.rules.DEFAULT_BUNDLED_RULES_DIR`), a workspace
    file shadowing a bundled one by name. A bundled-only (Path B) workspace
    therefore carries rules with no ``.vaultspec/rules`` on disk, so the surface
    is satisfied whenever compilation over that union yields content. ``compile``
    reads files and writes nothing, preserving this module's read-only contract.
    """
    resolved = RuleManager(root, bundled_rules_dir=DEFAULT_BUNDLED_RULES_DIR).compile()
    return bool(resolved)


def _skill_present(skills_dir: Path, name: str) -> bool:
    """True when a declared skill is present as a directory or a markdown file.

    Accepts the provisioned skill shape (``<name>/SKILL.md``) or a flat
    ``<name>.md`` procedure document.
    """
    if (skills_dir / name / "SKILL.md").is_file():
        return True
    return (skills_dir / f"{name}.md").is_file()


def _cli_resolvable() -> bool:
    """True when the vaultspec-core CLI resolves in the current environment.

    Resolution only, never a spawn: the console script on PATH, or the ``uvx``
    shim that runs ``uvx --from vaultspec-core vaultspec-core`` (ws5 recipe).
    """
    return any(shutil.which(name) is not None for name in _CLI_NAMES)
