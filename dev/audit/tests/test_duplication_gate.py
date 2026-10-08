"""The duplication module's own guards: Q.2's blocking gate and its baseline.

The adjudication judgement - which clones are known, which are new, which
baseline entries no longer match anything - is a pure function of typed data
(:func:`dev.audit.duplication.diff_against_baseline`), proven here directly
with no jscpd invocation and no network call. The one test that does invoke
the real scanner locks the live repository's state: it is the test this
Step's real-tree runs (red on a scratch clone, green on the committed tree)
stand behind.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest

from dev.audit import duplication as dup
from dev.paths import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path


def _group(
    lines: int,
    first: tuple[str, int],
    second: tuple[str, int],
    *,
    digest: str = "digest",
) -> dup.CloneGroup:
    return dup.CloneGroup(
        lines=lines,
        first_path=first[0],
        first_start=first[1],
        second_path=second[0],
        second_start=second[1],
        fragment_sha256=digest,
    )


def _baseline(*entries: dup.BaselineEntry, categories: dict[str, str]) -> dup.Baseline:
    return dup.Baseline(categories=categories, entries=tuple(entries))


def _entry(
    lines: int,
    first: tuple[str, int],
    second: tuple[str, int],
    *,
    category: str,
    digest: str = "digest",
) -> dup.BaselineEntry:
    return dup.BaselineEntry(
        category=category,
        lines=lines,
        first_path=first[0],
        first_start=first[1],
        second_path=second[0],
        second_start=second[1],
        fragment_sha256=digest,
    )


REASON = "a reason"
CATEGORIES = {"cat": REASON}


def test_a_clone_matching_a_baseline_entry_is_neither_new_nor_stale() -> None:
    group = _group(25, ("a.py", 1), ("b.py", 10))
    entry = _entry(25, ("a.py", 1), ("b.py", 10), category="cat")
    baseline = _baseline(entry, categories=CATEGORIES)
    new, stale = dup.diff_against_baseline([group], baseline)
    assert new == ()
    assert stale == ()


def test_a_clone_absent_from_the_baseline_is_new() -> None:
    group = _group(25, ("a.py", 1), ("b.py", 10))
    new, stale = dup.diff_against_baseline([group], _baseline(categories={}))
    assert new == (group,)
    assert stale == ()


def test_a_baseline_entry_matching_nothing_is_stale() -> None:
    """The code the entry described moved, or the duplicate was fixed."""
    entry = _entry(25, ("a.py", 1), ("b.py", 10), category="cat")
    new, stale = dup.diff_against_baseline([], _baseline(entry, categories=CATEGORIES))
    assert new == ()
    assert stale == (entry,)


def test_matching_is_unordered_in_first_and_second() -> None:
    """jscpd's own first/second ordering is not a stable identity to lean on."""
    group = _group(25, ("b.py", 10), ("a.py", 1))
    entry = _entry(25, ("a.py", 1), ("b.py", 10), category="cat")
    baseline = _baseline(entry, categories=CATEGORIES)
    new, stale = dup.diff_against_baseline([group], baseline)
    assert new == ()
    assert stale == ()


def test_a_different_span_at_the_same_lines_does_not_match() -> None:
    """The span is part of the identity: a shrunk or grown clone is a change."""
    group = _group(30, ("a.py", 1), ("b.py", 10))
    entry = _entry(25, ("a.py", 1), ("b.py", 10), category="cat")
    baseline = _baseline(entry, categories=CATEGORIES)
    new, stale = dup.diff_against_baseline([group], baseline)
    assert new == (group,)
    assert stale == (entry,)


def test_an_entry_still_matches_after_its_clone_moves_down_the_file() -> None:
    """Identity is content: an unrelated edit above a clone must not stale it."""
    group = _group(25, ("a.py", 41), ("b.py", 60), digest="same-fragment")
    entry = _entry(
        25, ("a.py", 1), ("b.py", 10), category="cat", digest="same-fragment"
    )
    baseline = _baseline(entry, categories=CATEGORIES)
    new, stale = dup.diff_against_baseline([group], baseline)
    assert new == ()
    assert stale == ()


def test_an_entry_stops_matching_when_one_token_of_the_fragment_changes() -> None:
    """A clone whose code changes must still stop matching, even at the same lines."""
    group = _group(25, ("a.py", 1), ("b.py", 10), digest="changed-fragment")
    entry = _entry(
        25, ("a.py", 1), ("b.py", 10), category="cat", digest="original-fragment"
    )
    baseline = _baseline(entry, categories=CATEGORIES)
    new, stale = dup.diff_against_baseline([group], baseline)
    assert new == (group,)
    assert stale == (entry,)


def test_load_baseline_reads_a_well_formed_file(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(
            {
                "categories": {"cat": REASON},
                "accepted": [
                    {
                        "category": "cat",
                        "lines": 25,
                        "first": {"path": "a.py", "start": 1},
                        "second": {"path": "b.py", "start": 10},
                        "fragment_sha256": "deadbeef",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    baseline = dup.load_baseline(path)
    assert baseline.categories == {"cat": REASON}
    assert len(baseline.entries) == 1
    assert baseline.entries[0].category == "cat"
    assert baseline.entries[0].fragment_sha256 == "deadbeef"


def test_load_baseline_refuses_a_category_with_no_reason(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    payload: dict[str, object] = {"categories": {"cat": ""}, "accepted": []}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty string reason"):
        dup.load_baseline(path)


def test_load_baseline_refuses_an_entry_naming_an_undeclared_category(
    tmp_path: Path,
) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(
            {
                "categories": {},
                "accepted": [
                    {
                        "category": "ghost",
                        "lines": 25,
                        "first": {"path": "a.py", "start": 1},
                        "second": {"path": "b.py", "start": 10},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="undeclared category"):
        dup.load_baseline(path)


def test_parse_report_digest_ignores_trailing_whitespace_but_not_content() -> None:
    """The digest normalises trailing whitespace per line; everything else is exact."""

    def _payload(fragment: str) -> dict[str, object]:
        return {
            "statistics": {"total": {"sources": 2, "percentage": 1.0}},
            "duplicates": [
                {
                    "lines": 2,
                    "fragment": fragment,
                    "firstFile": {"name": "a.py", "start": 1},
                    "secondFile": {"name": "b.py", "start": 10},
                }
            ],
        }

    base = dup.parse_report(_payload("line one\nline two")).groups[0].fragment_sha256
    trailing_ws = (
        dup.parse_report(_payload("line one  \nline two\t")).groups[0].fragment_sha256
    )
    changed = dup.parse_report(_payload("line one\nline TWO")).groups[0].fragment_sha256
    assert trailing_ws == base
    assert changed != base


def test_the_committed_baseline_loads_and_every_entry_has_a_reason() -> None:
    """The real file this gate ships, parsed the same way the gate parses it."""
    baseline = dup.load_baseline(dup.BASELINE_PATH)
    assert baseline.entries
    for entry in baseline.entries:
        assert baseline.categories[entry.category].strip()


def test_the_pinned_version_matches_package_json() -> None:
    """:data:`JSCPD_VERSION` and the exact devDependency must name one version."""
    payload = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    assert payload["devDependencies"]["jscpd"] == dup.JSCPD_VERSION


def test_the_blocking_gate_passes_against_the_real_repository() -> None:
    """The real scan, real baseline, real tree - this Step's locking test.

    Exit green here is the claim this Step makes: every tier plus dev/ holds
    no clone the baseline does not already name, and every baseline entry
    still points at a real clone. A new, unadjudicated copy anywhere in
    either tree fails this test the same way it fails the CI gate.
    """
    result = dup.run_blocking_duplication_scan()
    assert result.outcome is not dup.DuplicationOutcome.UNAVAILABLE, result.reason
    assert result.new_clones == (), dup.render_blocking_report(result)
    assert result.stale_entries == (), dup.render_blocking_report(result)
    assert result.baseline_size == len(dup.load_baseline().entries)


def test_render_blocking_report_names_every_new_and_stale_entry() -> None:
    group = _group(25, ("a.py", 1), ("b.py", 10))
    entry = _entry(30, ("c.py", 1), ("d.py", 10), category="cat")
    result = dup.BlockingDuplicationResult(
        outcome=dup.DuplicationOutcome.CLONES,
        baseline_size=1,
        new_clones=(group,),
        stale_entries=(entry,),
    )
    report = dup.render_blocking_report(result)
    assert re.search(r"NEW\s+25 lines\s+a\.py:1\s+<->\s+b\.py:10", report)
    assert "STALE  [cat] c.py:1  <->  d.py:10" in report
