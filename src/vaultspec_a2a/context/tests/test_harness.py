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
) -> None:
    """Write a minimal but real ``.vaultspec/`` corpus into *root*."""
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


def test_fully_provisioned_workspace_is_ready(tmp_path: Path) -> None:
    _provision(tmp_path)
    verdict = verify_harness(tmp_path)
    assert verdict.ready is True
    assert verdict.reasons == []


def test_absent_rules_corpus_is_a_reason(tmp_path: Path) -> None:
    _provision(tmp_path, rules=False)
    verdict = verify_harness(tmp_path)
    assert verdict.ready is False
    assert any("rules corpus" in r for r in verdict.reasons)


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
