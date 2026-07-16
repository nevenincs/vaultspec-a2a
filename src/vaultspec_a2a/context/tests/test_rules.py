"""Tests for context/rules.py — RuleManager (ADR-028).

All tests use real temp directories (tmp_path). No mocks, no monkeypatching.
"""

import shutil
import time
from pathlib import Path

import pytest

from vaultspec_a2a.context.rules import DEFAULT_BUNDLED_RULES_DIR, RuleManager


def _rules_dir(tmp_path: Path) -> Path:
    """Create and return the FLAT .vaultspec/rules/ directory under tmp_path.

    The rule corpus lives directly under ``.vaultspec/rules/`` in the current
    vaultspec-core schema (no nested ``rules/rules/``); the fixtures mirror that
    real layout (graph-agent-framework-harness P02.S13).
    """
    d = tmp_path / ".vaultspec" / "rules"
    d.mkdir(parents=True)
    return d


def _find_synced_rules_root() -> Path | None:
    """Locate a real workspace whose ``.vaultspec/rules/`` holds synced ``*.md``.

    Walks up from this test file to the first ancestor carrying a populated flat
    rule corpus. Returns ``None`` when no synced corpus is present (e.g. a bare
    checkout without ``vaultspec-core install``), so the real-corpus test can skip
    honestly rather than fabricate the layout.
    """
    for ancestor in Path(__file__).resolve().parents:
        rules_dir = ancestor / ".vaultspec" / "rules"
        if rules_dir.is_dir() and any(rules_dir.glob("*.md")):
            return ancestor
    return None


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


class TestRealSyncedCorpus:
    """Prove the fix against the ACTUAL synced flat rule corpus (P02.S13).

    Not a hand-built fixture: this points ``RuleManager`` at the repository's real
    ``.vaultspec/rules/`` corpus as ``vaultspec-core`` synced it. Before the
    path-alignment fix, ``_RULES_SUBDIR`` targeted a nonexistent nested
    ``rules/rules/`` directory, so ``compile()`` returned ``None`` against this
    same real corpus and these assertions would have failed - this is the
    regression that catches the defect. Skips honestly where no corpus is synced
    (a bare checkout without ``vaultspec-core install``).
    """

    def test_compile_returns_real_corpus_content(self) -> None:
        root = _find_synced_rules_root()
        if root is None:
            pytest.skip(
                "no synced .vaultspec/rules/ corpus found in any ancestor; run "
                "`vaultspec-core install` to materialize the flat rule corpus"
            )

        result = RuleManager(root).compile()

        # The defect made this None (nested path missing); the fix makes it real.
        assert result is not None, (
            "compile() returned None against the real synced corpus - the flat "
            "rules path is misaligned"
        )
        assert result.strip(), "compiled rule text is empty"
        # Stable content from the real non-builtin corpus (01-core.md).
        assert "Core Mandates" in result

    def test_discover_reads_flat_corpus_and_excludes_builtin(self) -> None:
        root = _find_synced_rules_root()
        if root is None:
            pytest.skip(
                "no synced .vaultspec/rules/ corpus found in any ancestor; run "
                "`vaultspec-core install` to materialize the flat rule corpus"
            )

        default = RuleManager(root).discover()
        with_builtin = RuleManager(root, include_builtin=True).discover()

        # The flat path finds the real corpus (non-empty); every hit is a direct
        # child of .vaultspec/rules/ (flat, not nested); and .builtin.md files are
        # excluded by default but admitted with the flag - the exclusion behaviour
        # holds on the real corpus, not just fixtures.
        assert default, "discover() found no rule files in the real flat corpus"
        rules_dir = (root / ".vaultspec" / "rules").resolve()
        for path in default:
            assert path.parent == rules_dir
            assert not path.name.endswith(".builtin.md")
        assert len(with_builtin) > len(default)
        assert any(p.name.endswith(".builtin.md") for p in with_builtin)

    def test_role_scope_is_subset_of_whole_corpus_on_real_corpus(self) -> None:
        """On the real corpus a scoped set is always a SUBSET of the whole corpus.

        Role scoping opts in, never adds: ``discover(role)`` can only ever return a
        subset of ``discover(None)``. Today no shipped rule carries a ``roles:``
        key, so a scoped turn is empty until the document-authoring rule source
        (P02.S03) lands - which is exactly the point: the mechanism is inert on the
        current corpus and turns on only for files that opt in.
        """
        root = _find_synced_rules_root()
        if root is None:
            pytest.skip(
                "no synced .vaultspec/rules/ corpus found in any ancestor; run "
                "`vaultspec-core install` to materialize the flat rule corpus"
            )
        rm = RuleManager(root)
        whole = {p.name for p in rm.discover(None)}
        scoped = {p.name for p in rm.discover("researcher")}
        assert scoped <= whole


def _write_rule(directory: Path, name: str, roles, body: str = "body") -> None:
    """Write a rule file with an optional ``roles:`` frontmatter list.

    ``roles=None`` writes a file with frontmatter but NO ``roles:`` key (not
    role-scoped); a list writes a ``roles:`` sequence; a string writes a bare
    scalar ``roles:`` value.
    """
    if roles is None:
        front = "order: 1\n"
    elif isinstance(roles, str):
        front = f"order: 1\nroles: {roles}\n"
    else:
        front = "order: 1\nroles:\n" + "".join(f"  - {r}\n" for r in roles)
    (directory / name).write_text(f"---\n{front}---\n\n{body}\n", encoding="utf-8")


class TestRoleScoping:
    """Opt-in ``role`` filter on discover/compile (P02.S04).

    Real temp dirs, no mocks. Scoping is opt-in and restrictive: only files whose
    ``roles:`` frontmatter includes the role are selected for a scoped turn, and
    ``role=None`` preserves the unchanged whole-corpus behaviour.
    """

    def test_discover_role_selects_only_opted_in_files(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        _write_rule(d, "doc.md", ["researcher", "adr-author"])
        _write_rule(d, "coder.md", ["standard-executor"])
        _write_rule(d, "untagged.md", None)
        rm = RuleManager(tmp_path)
        assert {p.name for p in rm.discover("researcher")} == {"doc.md"}
        assert {p.name for p in rm.discover("adr-author")} == {"doc.md"}
        assert {p.name for p in rm.discover("standard-executor")} == {"coder.md"}
        # A file with no roles: key (untagged) is excluded from every scoped turn.
        assert rm.discover("doc-reviewer") == []

    def test_discover_none_returns_whole_corpus_unchanged(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        _write_rule(d, "doc.md", ["researcher"])
        _write_rule(d, "untagged.md", None)
        (d / "x.builtin.md").write_text("builtin", encoding="utf-8")
        rm = RuleManager(tmp_path)
        # role=None and the default are identical: every non-builtin file, tagged
        # or not - the scoping is genuinely opt-in, not a behaviour change.
        assert {p.name for p in rm.discover()} == {"doc.md", "untagged.md"}
        assert {p.name for p in rm.discover(None)} == {"doc.md", "untagged.md"}

    def test_compile_role_compiles_only_scoped_subset(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        _write_rule(d, "doc.md", ["researcher"], body="DOC ONLY")
        _write_rule(d, "coder.md", ["standard-executor"], body="CODER ONLY")
        out = RuleManager(tmp_path).compile("researcher")
        assert out is not None
        assert "DOC ONLY" in out
        assert "CODER ONLY" not in out

    def test_compile_none_for_role_with_no_opted_in_files(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        _write_rule(d, "doc.md", ["researcher"])
        assert RuleManager(tmp_path).compile("doc-reviewer") is None

    def test_per_role_cache_does_not_cross_serve(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        _write_rule(d, "doc.md", ["researcher"], body="DOC")
        _write_rule(d, "coder.md", ["standard-executor"], body="CODER")
        rm = RuleManager(tmp_path)
        researcher = rm.compile("researcher")
        coder = rm.compile("standard-executor")
        whole = rm.compile(None)
        assert researcher is not None
        assert "DOC" in researcher and "CODER" not in researcher
        assert coder is not None
        assert "CODER" in coder and "DOC" not in coder
        assert whole is not None
        assert "DOC" in whole and "CODER" in whole
        # Cached second calls serve the SAME per-role string (no cross-contamination).
        assert rm.compile("researcher") == researcher
        assert rm.compile("standard-executor") == coder

    def test_corpus_change_invalidates_every_role_cache(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        _write_rule(d, "doc.md", ["researcher"], body="V1")
        rm = RuleManager(tmp_path)
        assert "V1" in (rm.compile("researcher") or "")
        # A new file lands for a DIFFERENT role; the dir mtime changes.
        time.sleep(0.01)
        _write_rule(d, "coder.md", ["standard-executor"], body="CODER")
        # The researcher cache is dropped and recomputed - still correct - and the
        # new role now resolves too (whole-corpus mtime watch, not per-role).
        assert "V1" in (rm.compile("researcher") or "")
        assert "CODER" in (rm.compile("standard-executor") or "")

    def test_bare_string_roles_value_is_honoured(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        _write_rule(d, "one.md", "researcher")  # scalar, not a list
        assert {p.name for p in RuleManager(tmp_path).discover("researcher")} == {
            "one.md"
        }

    def test_no_frontmatter_file_is_never_scoped(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        (d / "plain.md").write_text("no frontmatter at all", encoding="utf-8")
        rm = RuleManager(tmp_path)
        assert rm.discover("researcher") == []
        # ...but role=None still sees it (whole corpus).
        assert {p.name for p in rm.discover(None)} == {"plain.md"}


class TestBundledDefaults:
    """Bundled-default plus workspace-override read path (P02.S03, Path B).

    Real temp dirs, no mocks. Mirrors ``team_config``'s preset resolution: a
    workspace file SHADOWS a bundled file of the same name entirely (no merging);
    ``bundled_rules_dir=None`` is workspace-only.
    """

    def test_shipped_conventions_reach_a_bare_workspace_with_role_scope(
        self, tmp_path: Path
    ) -> None:
        """Whole-chain: a workspace with NO .vaultspec rules still compiles the
        shipped document-authoring conventions for a document persona role."""
        # A real tmp workspace, entirely bare - no .vaultspec/rules/ at all.
        rm = RuleManager(tmp_path, bundled_rules_dir=DEFAULT_BUNDLED_RULES_DIR)
        out = rm.compile("researcher")
        assert out is not None
        assert "Tag taxonomy" in out  # a stable heading from the shipped bundled file
        # Every one of the four document roles receives it...
        for role in ("researcher", "synthesist", "adr-author", "doc-reviewer"):
            assert rm.compile(role) is not None
        # ...and a non-document role does NOT (the file opts into doc roles only).
        assert rm.compile("standard-executor") is None

    def test_workspace_file_shadows_bundled_entirely(self, tmp_path: Path) -> None:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        _write_rule(bundled, "conv.md", ["researcher"], body="BUNDLED CONTENT")
        ws_rules = _rules_dir(tmp_path)
        _write_rule(ws_rules, "conv.md", ["researcher"], body="WORKSPACE OVERRIDE")
        rm = RuleManager(tmp_path, bundled_rules_dir=bundled)
        out = rm.compile("researcher")
        assert out is not None
        assert "WORKSPACE OVERRIDE" in out
        assert "BUNDLED CONTENT" not in out
        # Exactly one file resolves for the name - shadow, never merge.
        assert [p.name for p in rm.discover("researcher")] == ["conv.md"]

    def test_shadow_is_by_name_not_by_role(self, tmp_path: Path) -> None:
        # Bundled file opts into researcher; a same-named workspace file opts into a
        # DIFFERENT role. The workspace file wins ENTIRELY, so the bundled file is
        # gone and 'researcher' no longer resolves it.
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        _write_rule(bundled, "conv.md", ["researcher"], body="BUNDLED")
        ws_rules = _rules_dir(tmp_path)
        _write_rule(ws_rules, "conv.md", ["adr-author"], body="WS")
        rm = RuleManager(tmp_path, bundled_rules_dir=bundled)
        assert rm.discover("researcher") == []
        assert [p.name for p in rm.discover("adr-author")] == ["conv.md"]

    def test_role_none_unions_bundled_and_workspace(self, tmp_path: Path) -> None:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        _write_rule(bundled, "b.md", ["researcher"], body="BUNDLED")
        ws_rules = _rules_dir(tmp_path)
        _write_rule(ws_rules, "w.md", None, body="WORKSPACE")
        rm = RuleManager(tmp_path, bundled_rules_dir=bundled)
        whole = rm.compile(None)
        assert whole is not None
        assert "BUNDLED" in whole and "WORKSPACE" in whole

    def test_bundled_dir_change_invalidates_cache(self, tmp_path: Path) -> None:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        _write_rule(bundled, "b.md", ["researcher"], body="V1")
        rm = RuleManager(tmp_path, bundled_rules_dir=bundled)
        assert "V1" in (rm.compile("researcher") or "")
        time.sleep(0.01)
        _write_rule(bundled, "b.md", ["researcher"], body="V2")
        assert "V2" in (rm.compile("researcher") or "")

    def test_none_bundled_is_workspace_only(self, tmp_path: Path) -> None:
        ws_rules = _rules_dir(tmp_path)
        _write_rule(ws_rules, "w.md", ["researcher"], body="WS")
        rm = RuleManager(tmp_path)  # bundled_rules_dir defaults to None
        assert [p.name for p in rm.discover("researcher")] == ["w.md"]
        # A bare workspace with neither source resolves nothing.
        assert RuleManager(tmp_path / "empty").compile("researcher") is None


def _write_ordered(directory: Path, name: str, order: object, body: str) -> None:
    """Write a rule file with an optional ``order:`` frontmatter key."""
    front = "" if order is None else f"order: {order}\n"
    (directory / name).write_text(f"---\n{front}---\n\n{body}\n", encoding="utf-8")


class TestCompileOrderAndCacheEdges:
    """Compile order honors ``order:`` and the cache watches both source dirs.

    Reviewer LOW-3 (the ``order:`` key was declared but never consumed) and LOW-4
    (two uncovered cache-invalidation edges). Real temp dirs, no mocks.
    """

    def test_compile_honors_order_key_over_name(self, tmp_path: Path) -> None:
        d = _rules_dir(tmp_path)
        # Names sort b < a, but order: makes A-BODY (order 1) precede B-BODY (10).
        _write_ordered(d, "b_low.md", 1, "A-BODY")
        _write_ordered(d, "a_high.md", 10, "B-BODY")
        out = RuleManager(tmp_path).compile()
        assert out is not None
        assert out.index("A-BODY") < out.index("B-BODY")

    def test_undeclared_order_defaults_after_low_and_ties_by_name(
        self, tmp_path: Path
    ) -> None:
        d = _rules_dir(tmp_path)
        _write_ordered(d, "z_first.md", 1, "FIRST")  # low order wins despite name
        _write_ordered(d, "a_none.md", None, "UNDECLARED_A")  # default 100
        _write_ordered(d, "b_none.md", None, "UNDECLARED_B")  # default 100, name tie
        out = RuleManager(tmp_path).compile()
        assert out is not None
        assert (
            out.index("FIRST") < out.index("UNDECLARED_A") < out.index("UNDECLARED_B")
        )

    def test_cache_invalidates_when_bundled_file_disappears(
        self, tmp_path: Path
    ) -> None:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        _write_rule(bundled, "b.md", ["researcher"], body="BUNDLED")
        rm = RuleManager(tmp_path, bundled_rules_dir=bundled)
        assert "BUNDLED" in (rm.compile("researcher") or "")
        # The bundled file disappears while the bundled dir is still set.
        time.sleep(0.01)
        (bundled / "b.md").unlink()
        # Cache is invalidated (per-file mtime tier catches the removal), so the
        # role now resolves nothing rather than serving the stale bundled body.
        assert rm.compile("researcher") is None

    def test_cache_invalidates_on_workspace_change_while_bundled_set(
        self, tmp_path: Path
    ) -> None:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        _write_rule(bundled, "b.md", ["researcher"], body="BUNDLED")
        ws_rules = _rules_dir(tmp_path)
        rm = RuleManager(tmp_path, bundled_rules_dir=bundled)
        first = rm.compile(None)
        assert first is not None and "BUNDLED" in first and "WSNEW" not in first
        # A new workspace file appears while the bundled dir is also a source: the
        # candidate-dirs union in _has_changes must see the workspace dir change.
        time.sleep(0.01)
        _write_rule(ws_rules, "w.md", None, body="WSNEW")
        second = rm.compile(None)
        assert second is not None and "WSNEW" in second and "BUNDLED" in second
