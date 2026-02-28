"""Tests for the context preamble builder (ADR-014 §2.3)."""

from langchain_core.messages import SystemMessage

from ..metadata import ContextRef, ThreadMetadata
from ..preamble import build_context_preamble


class TestBuildContextPreamble:
    """Tests for build_context_preamble."""

    def test_returns_system_message(self) -> None:
        """Result must be a SystemMessage instance."""
        meta = ThreadMetadata(workspace_root="Y:/code/vaultspec")
        result = build_context_preamble(meta)
        assert isinstance(result, SystemMessage)

    def test_minimal_preamble_workspace_only(self) -> None:
        """Minimal preamble with only workspace_root."""
        meta = ThreadMetadata(workspace_root="Y:/code/vaultspec")
        result = build_context_preamble(meta)
        content = str(result.content)
        assert "## Project Context" in content
        assert "Y:/code/vaultspec" in content

    def test_includes_feature_tag(self) -> None:
        """Feature tag appears in the preamble when provided."""
        meta = ThreadMetadata(
            workspace_root="Y:/code/vaultspec",
            feature_tag="auth-flow",
        )
        result = build_context_preamble(meta)
        content = str(result.content)
        assert "auth-flow" in content
        assert "**Feature:**" in content

    def test_includes_source_repo(self) -> None:
        """Source repo appears in the preamble when provided."""
        meta = ThreadMetadata(
            workspace_root="Y:/code/vaultspec",
            source_repo="github.com/org/vaultspec",
        )
        result = build_context_preamble(meta)
        content = str(result.content)
        assert "github.com/org/vaultspec" in content
        assert "**Repository:**" in content

    def test_includes_source_branch(self) -> None:
        """Source branch appears in the preamble when provided."""
        meta = ThreadMetadata(
            workspace_root="Y:/code/vaultspec",
            source_branch="feat/auth-flow",
        )
        result = build_context_preamble(meta)
        content = str(result.content)
        assert "feat/auth-flow" in content
        assert "**Branch:**" in content

    def test_full_preamble_all_fields(self) -> None:
        """All fields appear when fully populated."""
        refs = [
            ContextRef(
                path=".vault/research/auth-research.md",
                stage="research",
                summary="Auth flow analysis",
            ),
            ContextRef(
                path=".vault/plan/auth-plan.md",
                stage="plan",
            ),
        ]
        meta = ThreadMetadata(
            workspace_root="Y:/code/vaultspec",
            source_repo="github.com/org/vaultspec",
            source_branch="feat/auth-flow",
            feature_tag="auth-flow",
            context_refs=refs,
        )
        result = build_context_preamble(meta)
        content = str(result.content)

        assert "## Project Context" in content
        assert "Y:/code/vaultspec" in content
        assert "auth-flow" in content
        assert "github.com/org/vaultspec" in content
        assert "feat/auth-flow" in content
        assert "## Available Context Documents" in content
        assert "**[research]**" in content
        assert "auth-research.md" in content
        assert "Auth flow analysis" in content
        assert "**[plan]**" in content
        assert "auth-plan.md" in content

    def test_context_refs_without_summary(self) -> None:
        """Context refs without summaries omit the dash separator."""
        ref = ContextRef(path=".vault/adrs/014-auth.md", stage="adr")
        meta = ThreadMetadata(
            workspace_root="Y:/code/vaultspec",
            context_refs=[ref],
        )
        result = build_context_preamble(meta)
        content = str(result.content)
        assert "**[adr]** `.vault/adrs/014-auth.md`" in content
        # No trailing dash
        assert content.count(" — ") == 0

    def test_no_optional_fields_no_extra_lines(self) -> None:
        """When optional fields are empty, their lines are omitted."""
        meta = ThreadMetadata(workspace_root="Y:/code/vaultspec")
        result = build_context_preamble(meta)
        content = str(result.content)
        assert "**Feature:**" not in content
        assert "**Repository:**" not in content
        assert "**Branch:**" not in content
        assert "## Available Context Documents" not in content
