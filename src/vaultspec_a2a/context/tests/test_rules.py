"""Tests for context/rules.py — RuleManager (ADR-028).

All tests use real temp directories (tmp_path). No mocks, no monkeypatching.
"""

import shutil
import time
from pathlib import Path

from vaultspec_a2a.context.rules import RuleManager


def _rules_dir(tmp_path: Path) -> Path:
    """Create and return .vaultspec/rules/rules/ under tmp_path."""
    d = tmp_path / ".vaultspec" / "rules" / "rules"
    d.mkdir(parents=True)
    return d


class TestDiscover:
    def test_discover_finds_custom_rules(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "coding.md").write_text("use snake_case")
        (d / "testing.md").write_text("no mocks")

        result = RuleManager(tmp_path).discover()

        assert len(result) == 2
        names = {p.name for p in result}
        assert names == {"coding.md", "testing.md"}

    def test_discover_excludes_builtin_by_default(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "custom.md").write_text("custom rule")
        (d / "scaffold.builtin.md").write_text("builtin rule")

        result = RuleManager(tmp_path).discover()

        assert len(result) == 1
        assert result[0].name == "custom.md"

    def test_discover_includes_builtin_when_flag_set(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "custom.md").write_text("custom rule")
        (d / "scaffold.builtin.md").write_text("builtin rule")

        result = RuleManager(tmp_path, include_builtin=True).discover()

        assert len(result) == 2
        names = {p.name for p in result}
        assert names == {"custom.md", "scaffold.builtin.md"}

    def test_discover_empty_when_no_vaultspec_dir(self, tmp_path: Path) -> None:
        result = RuleManager(tmp_path).discover()
        assert result == []

    def test_discover_returns_sorted(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "zzz.md").write_text("z")
        (d / "aaa.md").write_text("a")
        (d / "mmm.md").write_text("m")

        result = RuleManager(tmp_path).discover()

        assert [p.name for p in result] == ["aaa.md", "mmm.md", "zzz.md"]


class TestCompile:
    def test_compile_returns_none_when_no_rules(self, tmp_path: Path) -> None:
        result = RuleManager(tmp_path).compile()
        assert result is None

    def test_compile_returns_none_when_rules_dir_empty(self, tmp_path: Path) -> None:
        _rules_dir(tmp_path)
        result = RuleManager(tmp_path).compile()
        assert result is None

    def test_compile_returns_none_when_all_content_empty(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "empty.md").write_text("   \n  ")
        result = RuleManager(tmp_path).compile()
        assert result is None

    def test_compile_strips_frontmatter(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "rules.md").write_text(
            "---\ntitle: My Rules\nauthor: dev\n---\nactual content"
        )

        result = RuleManager(tmp_path).compile()

        assert result is not None
        assert "actual content" in result
        assert "title:" not in result
        assert "---" not in result

    def test_compile_resolves_includes(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (tmp_path / "shared.md").write_text("shared content here")
        (d / "main.md").write_text("intro\n@shared.md\noutro")

        result = RuleManager(tmp_path).compile()

        assert result is not None
        assert "shared content here" in result
        assert "intro" in result
        assert "outro" in result

    def test_compile_handles_missing_include(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "main.md").write_text("before\n@nonexistent.md\nafter")

        result = RuleManager(tmp_path).compile()

        assert result is not None
        assert "<!-- ERROR: Missing include: nonexistent.md -->" in result
        assert "before" in result
        assert "after" in result

    def test_compile_rejects_path_traversal(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "main.md").write_text("@../../etc/passwd")

        result = RuleManager(tmp_path).compile()

        # Should replace with comment, not include actual file
        assert result is not None
        assert "<!-- ERROR: Path outside workspace:" in result
        # Must not contain any content from outside workspace
        assert "root:" not in (result or "")

    def test_compile_skips_url_includes(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "main.md").write_text(
            "before\n@https://example.com/rules.md\n@http://example.com/other.md\nafter"
        )

        result = RuleManager(tmp_path).compile()

        assert result is not None
        assert "@https://example.com/rules.md" in result
        assert "@http://example.com/other.md" in result
        assert "before" in result
        assert "after" in result

    def test_compile_normalizes_backslashes_in_include(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        sub = d / "sub"
        sub.mkdir()
        (sub / "helper.md").write_text("helper content")
        (d / "main.md").write_text("@sub\\helper.md")

        result = RuleManager(tmp_path).compile()

        assert result is not None
        assert "helper content" in result

    def test_compile_wraps_included_content_in_html_comments(
        self, tmp_path: Path
    ) -> None:
        d = _rules_dir(tmp_path)
        (tmp_path / "shared.md").write_text("shared content")
        (d / "main.md").write_text("@shared.md")

        result = RuleManager(tmp_path).compile()

        assert result is not None
        assert "<!-- Included from shared.md -->" in result
        assert "<!-- End of shared.md -->" in result
        assert "shared content" in result

    def test_compile_handles_circular_includes(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "a.md").write_text("A content\n@b.md")
        (d / "b.md").write_text("B content\n@a.md")

        # Should not raise or loop infinitely
        result = RuleManager(tmp_path).compile()

        assert result is not None
        assert "A content" in result
        assert "B content" in result

    def test_compile_concatenates_multiple_rules(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "aaa.md").write_text("first rule")
        (d / "bbb.md").write_text("second rule")
        (d / "ccc.md").write_text("third rule")

        result = RuleManager(tmp_path).compile()

        assert result is not None
        assert "first rule" in result
        assert "second rule" in result
        assert "third rule" in result
        # Double newlines between sections
        assert "\n\n" in result

    def test_compile_include_relative_to_including_file(self, tmp_path: Path) -> None:
        """Include resolved relative to the including file's directory first."""
        d = _rules_dir(tmp_path)
        sub = d / "sub"
        sub.mkdir()
        (sub / "helper.md").write_text("helper content")
        (d / "main.md").write_text("@sub/helper.md")

        result = RuleManager(tmp_path).compile()

        assert result is not None
        assert "helper content" in result


class TestCompileCache:
    """Tests for the mtime-based compile cache (HIGH-01)."""

    def test_second_call_returns_cached_result(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "rule.md").write_text("original content")

        mgr = RuleManager(tmp_path)
        first = mgr.compile()
        second = mgr.compile()

        assert first == second
        assert mgr._cache_valid is True

    def test_cache_detects_file_content_change(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        rule_file = d / "rule.md"
        rule_file.write_text("original content")

        mgr = RuleManager(tmp_path)
        first = mgr.compile()

        # Bump mtime by writing new content with a future timestamp
        time.sleep(0.05)
        rule_file.write_text("updated content")

        second = mgr.compile()

        assert second is not None
        assert "updated content" in second
        assert first != second

    def test_cache_detects_new_file_added(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "aaa.md").write_text("first rule")

        mgr = RuleManager(tmp_path)
        first = mgr.compile()

        time.sleep(0.05)
        (d / "bbb.md").write_text("second rule")

        second = mgr.compile()

        assert second is not None
        assert "second rule" in second
        assert first != second

    def test_cache_detects_file_removed(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "aaa.md").write_text("first rule")
        extra = d / "bbb.md"
        extra.write_text("second rule")

        mgr = RuleManager(tmp_path)
        first = mgr.compile()
        assert "second rule" in (first or "")

        time.sleep(0.05)
        extra.unlink()

        second = mgr.compile()

        assert second is not None
        assert "second rule" not in second

    def test_invalidate_forces_recompile(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "rule.md").write_text("original")

        mgr = RuleManager(tmp_path)
        mgr.compile()
        assert mgr._cache_valid is True

        mgr.invalidate()
        assert mgr._cache_valid is False

        result = mgr.compile()
        assert result is not None
        assert "original" in result
        assert mgr._cache_valid is True

    def test_cache_handles_rules_dir_disappearing(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "rule.md").write_text("content")

        mgr = RuleManager(tmp_path)
        first = mgr.compile()
        assert first is not None

        # Remove rules dir entirely
        shutil.rmtree(d)

        second = mgr.compile()
        assert second is None

    def test_cache_no_rules_stays_cached(self, tmp_path: Path) -> None:
        mgr = RuleManager(tmp_path)
        first = mgr.compile()
        assert first is None
        assert mgr._cache_valid is True

        second = mgr.compile()
        assert second is None
