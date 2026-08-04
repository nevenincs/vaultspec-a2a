"""Tests for the agent-harness verifier.

Real filesystem only: each test provisions (or under-provisions) a genuine
``.vaultspec/`` corpus in a ``tmp_path`` workspace and asserts the verdict.
``vaultspec-core`` CLI resolvability is exercised as it resolves in the real test
environment (no mock of ``shutil.which``); the CLI-missing reason is covered by
driving the ``required_templates``/``required_skills`` surfaces, which fail
independently of the tool surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..harness import DEFAULT_REQUIRED_TEMPLATES, verify_harness

if TYPE_CHECKING:
    from pathlib import Path


def _provision(
    root: Path,
    *,
    rules: bool = True,
    templates: tuple[str, ...] = DEFAULT_REQUIRED_TEMPLATES,
    skills: tuple[str, ...] = (),
    agents: bool = True,
    empty_agents: bool = False,
    mcps: bool = False,
) -> None:
    """Write a minimal but real ``.vaultspec/`` corpus into *root*.

    ``agents`` lays the agent-definition corpus a real ``vaultspec-core install``
    produces; ``empty_agents`` creates the directory without content, which is
    what a partial install leaves and what mere existence checks cannot tell
    apart from a complete one. ``mcps`` lays the server corpus an install also
    produces - off by default, because the verifier deliberately does not check
    it and the tests below prove its presence changes no verdict either way.
    """
    if rules:
        rules_dir = root / ".vaultspec" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "01-core.md").write_text("# core rules\n", encoding="utf-8")
    templates_dir = root / ".vaultspec" / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    for name in templates:
        (templates_dir / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
    for name in skills:
        skill_dir = root / ".vaultspec" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    if agents or empty_agents:
        agents_dir = root / ".vaultspec" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        if not empty_agents:
            (agents_dir / "vaultspec-adr-author.md").write_text(
                "# adr author\n", encoding="utf-8"
            )
    if mcps:
        mcps_dir = root / ".vaultspec" / "mcps"
        mcps_dir.mkdir(parents=True, exist_ok=True)
        (mcps_dir / "vaultspec-core.json").write_text("{}\n", encoding="utf-8")


def test_fully_provisioned_workspace_is_ready(tmp_path: Path) -> None:
    _provision(tmp_path)
    verdict = verify_harness(tmp_path)
    assert verdict.ready is True
    assert verdict.reasons == []


def test_missing_agents_corpus_is_a_reason(tmp_path: Path) -> None:
    """The framework's own agent definitions are part of the harness, not extras.

    An agent reaches the document rules - which record grounds a decision, which
    grounds a plan - through core's corpus rather than through prose restated in
    a persona. A workspace without it dispatches an agent working from
    definitions that are simply absent, with nothing anywhere reporting it.
    """
    _provision(tmp_path, agents=False)

    verdict = verify_harness(tmp_path)

    assert verdict.ready is False
    assert any("agents" in reason for reason in verdict.reasons)


def test_workspace_mcps_corpus_changes_no_verdict(tmp_path: Path) -> None:
    """The workspace server corpus is not a harness surface, present or absent.

    A run's MCP surface is resolved from the closed, in-package registry keyed by
    the names a team's ``[team.harness]`` declares; there is no discovery path
    from ``.vaultspec/mcps`` into composition. Verifying it therefore asserted a
    relationship the runtime does not have - failing runs on a corpus they never
    read, and passing ones while implying the project's declarations reached the
    agent. Both workspaces below are ready, and neither verdict mentions it.
    """
    without = tmp_path / "without-mcps"
    with_mcps = tmp_path / "with-mcps"
    without.mkdir()
    with_mcps.mkdir()
    _provision(without, mcps=False)
    _provision(with_mcps, mcps=True)

    absent = verify_harness(without)
    present = verify_harness(with_mcps)

    assert not (without / ".vaultspec" / "mcps").exists()
    assert (with_mcps / ".vaultspec" / "mcps" / "vaultspec-core.json").is_file()
    assert absent.ready is True
    assert present.ready is True
    assert absent.reasons == present.reasons == []


def test_an_empty_corpus_directory_is_not_provisioned(tmp_path: Path) -> None:
    """Presence is not the check; content is.

    A bare ``mkdir`` is what an interrupted install leaves behind, and it reads
    as provisioned to anything that only asks whether the path exists - which is
    exactly how a surface degrades silently.
    """
    _provision(tmp_path, agents=False, empty_agents=True)

    verdict = verify_harness(tmp_path)

    assert verdict.ready is False
    assert any("agents" in reason for reason in verdict.reasons)


def test_workspace_without_rules_corpus_is_satisfied_by_bundled_defaults(
    tmp_path: Path,
) -> None:
    """A workspace with no on-disk rules is rules-satisfied via bundled defaults.

    Post-Path-B (architect arbitration): rules are delivered in-process by the
    RuleManager as the union of the workspace corpus and the bundled defaults, so
    an absent ``.vaultspec/rules`` no longer fails the rules surface. With every
    template present, such a workspace is fully ready.
    """
    _provision(tmp_path, rules=False)
    verdict = verify_harness(tmp_path)
    assert verdict.ready is True
    assert not any("rule content" in r or "rules corpus" in r for r in verdict.reasons)


def test_bare_workspace_rules_satisfied_but_templates_missing(tmp_path: Path) -> None:
    """A bare workspace: rules pass on bundled defaults, but templates still fail.

    The bundled-only tripwire. A workspace with no ``.vaultspec`` at all is NOT
    refused on the rules surface (the bundled defaults resolve), but templates
    have no bundled fallback, so the verdict is not-ready for the TEMPLATES
    reason - never the rules reason. This is the arbitrated truth that replaces
    the pre-Path-B ``.vaultspec/rules`` on-disk probe.
    """
    verdict = verify_harness(tmp_path)
    assert verdict.ready is False
    assert not any("rule content" in r or "rules corpus" in r for r in verdict.reasons)
    assert any("templates missing" in r for r in verdict.reasons)


def test_missing_required_templates_are_named(tmp_path: Path) -> None:
    # Provision every canonical template except two, which must be named.
    present = tuple(t for t in DEFAULT_REQUIRED_TEMPLATES if t not in {"adr", "plan"})
    _provision(tmp_path, templates=present)
    verdict = verify_harness(tmp_path)
    assert verdict.ready is False
    reason = next(r for r in verdict.reasons if "templates missing" in r)
    assert "adr" in reason
    assert "plan" in reason
    # A present template is not falsely flagged.
    assert "research" not in reason


def test_declared_skill_absent_is_a_reason(tmp_path: Path) -> None:
    _provision(tmp_path, skills=("vaultspec-research",))
    verdict = verify_harness(
        tmp_path, required_skills=("vaultspec-research", "vaultspec-adr")
    )
    assert verdict.ready is False
    reason = next(r for r in verdict.reasons if "skills missing" in r)
    assert "vaultspec-adr" in reason
    # The provisioned skill is not flagged.
    assert "vaultspec-research" not in reason


def test_declared_skills_all_present_pass(tmp_path: Path) -> None:
    _provision(tmp_path, skills=("vaultspec-research", "vaultspec-adr"))
    verdict = verify_harness(
        tmp_path, required_skills=("vaultspec-research", "vaultspec-adr")
    )
    assert verdict.ready is True


def test_no_declared_skills_does_not_fail_on_skills(tmp_path: Path) -> None:
    """An empty required_skills list never contributes a skills reason."""
    _provision(tmp_path, skills=())
    verdict = verify_harness(tmp_path, required_skills=())
    assert not any("skills missing" in r for r in verdict.reasons)


def test_reasons_never_leak_a_filesystem_path(tmp_path: Path) -> None:
    """Safe reasons name WHAT is missing, never WHERE (no path leakage)."""
    _provision(tmp_path, rules=False, templates=())
    verdict = verify_harness(tmp_path, required_skills=("vaultspec-adr",))
    assert verdict.ready is False
    joined = " ".join(verdict.reasons)
    assert str(tmp_path) not in joined
    assert ".vaultspec/skills" not in joined
