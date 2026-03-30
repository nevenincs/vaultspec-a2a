"""Tests for thread metadata models and discovery utilities (ADR-014)."""

from pathlib import Path

import pytest

from vaultspec_a2a.context.metadata import (
    ContextRef,
    ThreadMetadata,
    discover_context_refs,
    generate_nickname,
)
from vaultspec_a2a.control.config import domain_config

# ---------------------------------------------------------------------------
# ContextRef validation
# ---------------------------------------------------------------------------


class TestContextRef:
    """Tests for ContextRef model validation."""

    def test_accepts_relative_path(self) -> None:
        """Relative paths are accepted."""
        ref = ContextRef(path=".vault/research/auth-research.md", stage="research")
        assert ref.path == ".vault/research/auth-research.md"

    def test_rejects_absolute_path(self) -> None:
        """Absolute paths (detected by the OS) are rejected."""
        # Use a path that is absolute on the current platform
        abs_path = str(Path.cwd() / ".vault" / "research" / "auth.md")
        with pytest.raises(ValueError, match="must be relative"):
            ContextRef(path=abs_path, stage="research")

    def test_summary_default_empty(self) -> None:
        """Summary defaults to empty string."""
        ref = ContextRef(path="doc.md", stage="plan")
        assert ref.summary == ""

    def test_summary_provided(self) -> None:
        """Summary can be explicitly set."""
        ref = ContextRef(path="doc.md", stage="adr", summary="Auth flow ADR")
        assert ref.summary == "Auth flow ADR"


# ---------------------------------------------------------------------------
# ThreadMetadata validation
# ---------------------------------------------------------------------------


class TestThreadMetadata:
    """Tests for ThreadMetadata model validation."""

    def test_valid_nickname(self) -> None:
        """Valid slug nicknames are accepted."""
        meta = ThreadMetadata(
            nickname="auth-flow-star-a3f2",
            workspace_root="Y:/code/vaultspec",
        )
        assert meta.nickname == "auth-flow-star-a3f2"

    def test_empty_nickname_allowed(self) -> None:
        """Empty nickname (auto-generate later) is allowed."""
        meta = ThreadMetadata(nickname="", workspace_root="Y:/code/vaultspec")
        assert meta.nickname == ""

    def test_invalid_nickname_uppercase(self) -> None:
        """Uppercase letters are rejected in nicknames."""
        with pytest.raises(ValueError, match="valid slug"):
            ThreadMetadata(nickname="Auth-Flow", workspace_root="Y:/code/vaultspec")

    def test_invalid_nickname_too_short(self) -> None:
        """Two-character nicknames are rejected (minimum 3)."""
        with pytest.raises(ValueError, match="valid slug"):
            ThreadMetadata(nickname="ab", workspace_root="Y:/code/vaultspec")

    def test_invalid_nickname_special_chars(self) -> None:
        """Underscores and other special chars are rejected."""
        with pytest.raises(ValueError, match="valid slug"):
            ThreadMetadata(nickname="auth_flow", workspace_root="Y:/code/vaultspec")

    def test_nickname_three_chars_valid(self) -> None:
        """Three-character nicknames matching the pattern are valid."""
        meta = ThreadMetadata(nickname="abc", workspace_root="Y:/code/vaultspec")
        assert meta.nickname == "abc"

    def test_workspace_root_absolute_required(self) -> None:
        """Relative workspace_root paths are rejected."""
        with pytest.raises(ValueError, match="absolute path"):
            ThreadMetadata(workspace_root="relative/path")

    def test_workspace_root_absolute_accepted(self) -> None:
        """Absolute workspace_root paths are accepted."""
        meta = ThreadMetadata(workspace_root="Y:/code/vaultspec")
        assert meta.workspace_root == "Y:/code/vaultspec"

    def test_optional_fields_default(self) -> None:
        """Optional fields default correctly."""
        meta = ThreadMetadata(workspace_root="Y:/code/vaultspec")
        assert meta.source_repo == ""
        assert meta.source_branch == ""
        assert meta.callee == ""
        assert meta.feature_tag == ""
        assert meta.context_refs == []

    def test_full_metadata(self) -> None:
        """All fields can be populated simultaneously."""
        ref = ContextRef(path=".vault/research/auth.md", stage="research")
        meta = ThreadMetadata(
            nickname="auth-flow-star-a3f2",
            workspace_root="Y:/code/vaultspec",
            source_repo="github.com/org/vaultspec",
            source_branch="feat/auth-flow",
            callee="claude-cli",
            feature_tag="auth-flow",
            context_refs=[ref],
        )
        assert meta.source_repo == "github.com/org/vaultspec"
        assert len(meta.context_refs) == 1


# ---------------------------------------------------------------------------
# discover_context_refs
# ---------------------------------------------------------------------------


class TestDiscoverContextRefs:
    """Tests for .vault/ document auto-discovery."""

    def test_discovers_research_docs(self, tmp_path: Path) -> None:
        """Documents matching the research glob are discovered."""
        research_dir = tmp_path / ".vault" / "research"
        research_dir.mkdir(parents=True)
        (research_dir / "2026-02-28-auth-flow-research.md").write_text("# Research")

        refs = discover_context_refs(tmp_path, "auth-flow")
        assert len(refs) == 1
        assert refs[0].stage == "research"
        assert "auth-flow" in refs[0].path

    def test_discovers_adr_docs(self, tmp_path: Path) -> None:
        """Documents matching the ADR glob are discovered."""
        adr_dir = tmp_path / ".vault" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "014-auth-flow.md").write_text("# ADR")

        refs = discover_context_refs(tmp_path, "auth-flow")
        assert len(refs) == 1
        assert refs[0].stage == "adr"

    def test_discovers_plan_docs(self, tmp_path: Path) -> None:
        """Documents matching the plan glob are discovered."""
        plan_dir = tmp_path / ".vault" / "plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "2026-02-28-auth-flow-plan.md").write_text("# Plan")

        refs = discover_context_refs(tmp_path, "auth-flow")
        assert len(refs) == 1
        assert refs[0].stage == "plan"

    def test_discovers_exec_docs(self, tmp_path: Path) -> None:
        """Documents matching the exec glob (nested) are discovered."""
        exec_dir = tmp_path / ".vault" / "exec" / "2026-02-28-auth-flow"
        exec_dir.mkdir(parents=True)
        (exec_dir / "2026-02-28-auth-flow-step1.md").write_text("# Step 1")
        (exec_dir / "2026-02-28-auth-flow-review.md").write_text("# Review")

        refs = discover_context_refs(tmp_path, "auth-flow")
        assert len(refs) == 2
        assert all(r.stage == "exec" for r in refs)

    def test_discovers_multiple_stages(self, tmp_path: Path) -> None:
        """Documents across multiple stages are all discovered."""
        for subdir in ("research", "adr", "plan"):
            d = tmp_path / ".vault" / subdir
            d.mkdir(parents=True)
            (d / f"auth-flow-{subdir}.md").write_text(f"# {subdir}")

        refs = discover_context_refs(tmp_path, "auth-flow")
        stages = {r.stage for r in refs}
        assert stages == {"research", "adr", "plan"}

    def test_no_matching_docs(self, tmp_path: Path) -> None:
        """Empty result when no documents match the feature tag."""
        research_dir = tmp_path / ".vault" / "research"
        research_dir.mkdir(parents=True)
        (research_dir / "unrelated-topic.md").write_text("# Unrelated")

        refs = discover_context_refs(tmp_path, "auth-flow")
        assert refs == []

    def test_no_vault_directory(self, tmp_path: Path) -> None:
        """Empty result when .vault/ does not exist."""
        refs = discover_context_refs(tmp_path, "auth-flow")
        assert refs == []

    def test_caps_at_max_refs(self, tmp_path: Path) -> None:
        """Discovery stops at the settings.max_context_refs limit."""
        research_dir = tmp_path / ".vault" / "research"
        research_dir.mkdir(parents=True)
        for i in range(domain_config.max_context_refs + 10):
            (research_dir / f"auth-flow-doc-{i:04d}.md").write_text(f"# Doc {i}")

        refs = discover_context_refs(tmp_path, "auth-flow")
        assert len(refs) == domain_config.max_context_refs

    def test_paths_are_relative(self, tmp_path: Path) -> None:
        """Discovered paths are relative to workspace_root."""
        research_dir = tmp_path / ".vault" / "research"
        research_dir.mkdir(parents=True)
        (research_dir / "auth-flow-research.md").write_text("# Research")

        refs = discover_context_refs(tmp_path, "auth-flow")
        for ref in refs:
            assert not Path(ref.path).is_absolute()


# ---------------------------------------------------------------------------
# generate_nickname
# ---------------------------------------------------------------------------


class TestGenerateNickname:
    """Tests for nickname generation utility."""

    def test_with_feature_tag(self) -> None:
        """Feature tag produces {tag}-{topology}-{hash} format."""
        nick = generate_nickname("auth-flow", "star", "a3f2bcde")
        assert nick == "auth-flow-star-a3f2"

    def test_without_feature_tag(self) -> None:
        """Empty feature tag falls back to 'thread-{topology}-{hash}'."""
        nick = generate_nickname("", "pipeline", "b7c1ffee")
        assert nick == "thread-pipeline-b7c1"

    def test_short_thread_id(self) -> None:
        """Thread IDs shorter than 4 chars use what is available."""
        nick = generate_nickname("feat", "star", "ab")
        assert nick == "feat-star-ab"

    def test_different_topologies(self) -> None:
        """Topology name is embedded in the nickname."""
        nick_star = generate_nickname("feat", "star", "1234abcd")
        nick_pipe = generate_nickname("feat", "pipeline", "1234abcd")
        nick_loop = generate_nickname("feat", "pipeline-loop", "1234abcd")
        assert "star" in nick_star
        assert "pipeline" in nick_pipe
        assert "pipeline-loop" in nick_loop

    # --- M1 / TEST-M4: sanitization edge cases ---

    def test_uppercase_feature_tag_lowercased(self) -> None:
        """Uppercase feature_tag is lowercased so the slug is valid (M1)."""
        nick = generate_nickname("AUTH-FLOW", "star", "a3f2bcde")
        # Must be all lowercase to satisfy _NICKNAME_PATTERN
        assert nick == "auth-flow-star-a3f2"

    def test_feature_tag_with_special_chars_stripped(self) -> None:
        """Non-alphanumeric/hyphen chars in feature_tag are stripped (M1)."""
        nick = generate_nickname("auth_flow!@#", "star", "a3f2bcde")
        # underscores and special chars removed, leaving "authflow"
        assert nick == "authflow-star-a3f2"

    def test_feature_tag_all_special_chars_fallback(self) -> None:
        """feature_tag empty after sanitisation falls back to 'thread-' (M1)."""
        nick = generate_nickname("!!!", "star", "a3f2bcde")
        assert nick.startswith("thread-star-")

    def test_feature_tag_empty_string(self) -> None:
        """Empty feature_tag falls back to 'thread-{topology}-{hash}' (TEST-M4)."""
        nick = generate_nickname("", "star", "a3f2bcde")
        assert nick == "thread-star-a3f2"

    def test_feature_tag_with_consecutive_hyphens_collapsed(self) -> None:
        """Consecutive hyphens in feature_tag are collapsed to single hyphen (M1)."""
        nick = generate_nickname("auth--flow", "star", "a3f2bcde")
        assert nick == "auth-flow-star-a3f2"

    def test_feature_tag_with_leading_trailing_hyphens_stripped(self) -> None:
        """Leading and trailing hyphens in feature_tag are stripped (M1)."""
        nick = generate_nickname("-auth-flow-", "star", "a3f2bcde")
        assert nick == "auth-flow-star-a3f2"

    def test_empty_thread_id_uses_zero_padding(self) -> None:
        """Empty thread_id falls back to '0000' suffix (TEST-M4)."""
        nick = generate_nickname("feat", "star", "")
        assert nick == "feat-star-0000"


# ---------------------------------------------------------------------------
# discover_context_refs: security edge cases (CORE-C3)
# ---------------------------------------------------------------------------


class TestDiscoverContextRefsSecurityEdgeCases:
    """Security edge cases for glob pattern injection via feature_tag."""

    def test_glob_metachar_asterisk_not_expanded(self, tmp_path: Path) -> None:
        """feature_tag with '*' does not wildcard-match unrelated files (C3)."""
        research_dir = tmp_path / ".vault" / "research"
        research_dir.mkdir(parents=True)
        (research_dir / "unrelated.md").write_text("# Unrelated")
        # feature_tag = "*" would match everything if not escaped
        refs = discover_context_refs(tmp_path, "*")
        # The escaped pattern ".vault/research/*[*]*.md" matches files
        # literally containing "*" — there are none, so empty result.
        assert refs == []

    def test_glob_metachar_question_mark_not_expanded(self, tmp_path: Path) -> None:
        """feature_tag with '?' does not single-char-wildcard match (C3)."""
        research_dir = tmp_path / ".vault" / "research"
        research_dir.mkdir(parents=True)
        (research_dir / "auth-flow-research.md").write_text("# Research")
        refs = discover_context_refs(tmp_path, "?")
        # "?" escaped so no match against "auth-flow-research.md"
        assert refs == []

    def test_glob_metachar_brackets_not_expanded(self, tmp_path: Path) -> None:
        """feature_tag '[a-z]' treated literally, not as character class (C3)."""
        research_dir = tmp_path / ".vault" / "research"
        research_dir.mkdir(parents=True)
        (research_dir / "auth-flow-research.md").write_text("# Research")
        refs = discover_context_refs(tmp_path, "[a-z]")
        # "[a-z]" escaped so no match against "auth-flow-research.md"
        assert refs == []

    def test_path_traversal_attempt_blocked(self, tmp_path: Path) -> None:
        """feature_tag with '..' does not traverse outside workspace (C3)."""
        # Create a file outside the workspace that would be matched if traversal worked
        secret_dir = tmp_path.parent / "secret"
        secret_dir.mkdir(exist_ok=True)
        (secret_dir / "secret.md").write_text("# Secret")
        refs = discover_context_refs(tmp_path, "../secret")
        # Path traversal blocked by glob.escape("../secret")
        assert refs == []
