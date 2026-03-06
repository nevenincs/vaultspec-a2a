"""Tests for build_anchoring_context (ADR-022)."""

from ..anchoring import _ANCHOR_PATH_CAP, build_anchoring_context


def _make_state(**overrides):
    """Minimal state dict with only the fields anchoring reads."""
    base = {
        "messages": [],
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "thread_id": "test",
        "token_usage": {},
        "next": "",
    }
    base.update(overrides)
    return base


class TestBuildAnchoringContext:
    """All branches of build_anchoring_context."""

    def test_returns_none_when_active_feature_missing(self) -> None:
        state = _make_state()
        assert build_anchoring_context(state) is None

    def test_returns_none_when_active_feature_is_none(self) -> None:
        state = _make_state(active_feature=None)
        assert build_anchoring_context(state) is None

    def test_returns_none_when_active_feature_is_empty(self) -> None:
        state = _make_state(active_feature="")
        assert build_anchoring_context(state) is None

    def test_basic_feature_name(self) -> None:
        state = _make_state(active_feature="auth-flow")
        result = build_anchoring_context(state)
        assert result is not None
        assert "## Active Feature Context" in result
        assert "**Feature:** auth-flow" in result

    def test_includes_phase_when_set(self) -> None:
        state = _make_state(active_feature="auth-flow", pipeline_phase="implement")
        result = build_anchoring_context(state)
        assert result is not None
        assert "**Phase:** implement" in result

    def test_excludes_phase_when_not_set(self) -> None:
        state = _make_state(active_feature="auth-flow")
        result = build_anchoring_context(state)
        assert result is not None
        assert "Phase" not in result

    def test_includes_vault_paths(self) -> None:
        state = _make_state(
            active_feature="auth-flow",
            vault_index={
                "research": ["docs/research/auth.md"],
                "adr": ["docs/adrs/001.md", "docs/adrs/002.md"],
            },
        )
        result = build_anchoring_context(state)
        assert result is not None
        assert "### Available Vault Documents" in result
        assert "**RESEARCH**" in result
        assert "`docs/research/auth.md`" in result
        assert "**ADR**" in result
        assert "`docs/adrs/001.md`" in result

    def test_vault_paths_capped_at_anchor_path_cap(self) -> None:
        paths = [f"docs/spec/{i}.md" for i in range(_ANCHOR_PATH_CAP + 5)]
        state = _make_state(
            active_feature="auth-flow",
            vault_index={"spec": paths},
        )
        result = build_anchoring_context(state)
        assert result is not None
        assert "(+ 5 more)" in result
        # The last visible path should be index _ANCHOR_PATH_CAP - 1
        assert f"`docs/spec/{_ANCHOR_PATH_CAP - 1}.md`" in result
        # The first over-cap path should NOT appear
        assert f"`docs/spec/{_ANCHOR_PATH_CAP}.md`" not in result

    def test_no_more_label_when_paths_within_cap(self) -> None:
        paths = [f"docs/spec/{i}.md" for i in range(3)]
        state = _make_state(
            active_feature="auth-flow",
            vault_index={"spec": paths},
        )
        result = build_anchoring_context(state)
        assert result is not None
        assert "more)" not in result

    def test_includes_validation_errors(self) -> None:
        state = _make_state(
            active_feature="auth-flow",
            validation_errors=["missing return type", "unused import"],
        )
        result = build_anchoring_context(state)
        assert result is not None
        assert "### Validation Errors (2 active)" in result
        assert "missing return type" in result
        assert "unused import" in result

    def test_no_errors_section_when_empty(self) -> None:
        state = _make_state(active_feature="auth-flow", validation_errors=[])
        result = build_anchoring_context(state)
        assert result is not None
        assert "Validation Errors" not in result

    def test_empty_vault_index(self) -> None:
        state = _make_state(active_feature="auth-flow", vault_index={})
        result = build_anchoring_context(state)
        assert result is not None
        assert "Available Vault Documents" not in result
