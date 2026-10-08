"""No live source may cite a recipe invocation, or a symbol, that is gone.

The harness has been through three renames: a nested module namespace, a
verb-plus-argument dispatch, and the flat hyphenated recipes the justfile
carries today. Each rename left citations behind - in a doc comment, a
workflow, a README, the text an error message prints - and each stale citation
sends its reader to a recipe that errors out.

There is no alias layer to soften that: a `just` alias binds one name to one
recipe and cannot carry an argument, so a two-token invocation has no shim and
never will. This sweep is the whole safety net, which is why it walks the tree
rather than a hand-written file list: the previous cutover swept a list, and
four citations survived it.

The second sweep below (Q.5b) is the same idea applied to a different kind of
rename: a class, function or module this remediation deleted outright rather
than renamed. The risk it guards against is different too - not a reader
following a stale doc comment, but a WRITER reaching for a shape they remember
and resurrecting the thing a prior round removed, under the same name, because
nothing told them it was gone.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from dev.paths import REPO_ROOT

pytestmark = pytest.mark.unit

#: Invocation prefixes that no longer exist.
#:
#: Assembled from fragments ON PURPOSE. Written as literals, the retired
#: strings would appear in this file and the sweep below would flag its own
#: source - the guard failing on itself is how the first version behaved.
RETIRED_INVOCATIONS: tuple[str, ...] = tuple(
    "just " + verb + " "
    for verb in (
        "lint",
        "fix",
        "audit",
        "test",
        "deps",
        "health",
        "dev",
        "prod",
    )
)

#: The contexts a real citation appears in. Bare prose is deliberately NOT one
#: of them: "or we can just test that the parser works" is English, not a stale
#: recipe, and an unanchored sweep flags it. Every genuine citation in these
#: trees is either inside backticks, a shell prompt, or a workflow `run:` step.
CITATION_CONTEXTS: tuple[str, ...] = ("`", "$ ", "run: ", "  ")


def _retired_citations() -> tuple[str, ...]:
    """Return every retired invocation as it would really be written."""
    return tuple(
        context + invocation
        for invocation in RETIRED_INVOCATIONS
        for context in CITATION_CONTEXTS
    )


#: Trees excluded from the sweep. `.vault/` records state what was true when
#: they were written and are deliberately never rewritten; the rest are
#: generated, vendored, cached, or build output.
CITATION_EXCLUDED: frozenset[str] = frozenset(
    {
        ".vault",
        ".git",
        ".venv",
        ".uv-cache",
        ".profile",
        "node_modules",
        "target",
        "dist",
        "dist-bin",
        "build",
        "tmp",
        "scratch",
        "scratchpad",
        "var",
        ".logs",
        "__pycache__",
        "_build",
        "locales",
        "site-packages",
    }
)

#: Suffixes worth sweeping. A retired invocation only misleads where a reader
#: or a runner will meet it.
CITATION_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".mjs",
        ".js",
        ".ts",
        ".tsx",
        ".rs",
        ".md",
        ".rst",
        ".toml",
        ".yml",
        ".yaml",
        ".json",
        ".ps1",
        ".sh",
    }
)


#: Where live citations can be. Bounded on purpose rather than walking the whole
#: checkout: a full `rglob` here traverses the virtual environment, the tool
#: caches and the generated documentation trees, which between them are orders
#: of magnitude larger than the source and carry no live citation at all.
SWEPT_ROOTS: tuple[str, ...] = (
    ".github",
    "dev",
    "docs",
    "engine",
    "frontend",
    "infra",
    "packaging",
    "schemas",
    "scripts",
    "service",
    "src",
    "tools",
    "typings",
)


def _sweepable(repo_root: Path) -> list[Path]:
    """Return every source file worth sweeping, under the bounded roots.

    Args:
        repo_root: The tree to sweep.

    Returns:
        Every sweepable file. Never empty for a real checkout: a corpus that
        globs to nothing would retire this guard silently, so the caller
        asserts on the count.
    """
    candidates: list[Path] = [path for path in repo_root.glob("*") if path.is_file()]
    for name in SWEPT_ROOTS:
        tree = repo_root / name
        if tree.is_dir():
            candidates.extend(tree.rglob("*"))
    sweepable = [
        path
        for path in candidates
        if path.is_file()
        and path.suffix in CITATION_SUFFIXES
        and not CITATION_EXCLUDED & set(path.relative_to(repo_root).parts)
    ]
    assert sweepable, (
        f"no sweepable source found under {repo_root}; an empty corpus retires "
        "this guard silently rather than failing it"
    )
    return sweepable


def test_no_live_source_cites_a_retired_invocation() -> None:
    """A doc comment or error message naming a retired form sends readers nowhere."""
    repo_root = REPO_ROOT
    swept = _sweepable(repo_root)
    assert len(swept) > 50, (
        f"the sweep found only {len(swept)} files under {SWEPT_ROOTS}; a corpus "
        "this small means a renamed tree retired the guard rather than failing it"
    )
    citations = _retired_citations()
    offenders: list[str] = []
    for path in swept:
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(citation in text for citation in citations):
            offenders.append(str(path.relative_to(repo_root)))
    assert not offenders, (
        f"these cite a retired invocation {RETIRED_INVOCATIONS}: {sorted(offenders)}"
    )


def test_the_sweep_can_actually_fail(tmp_path: Path) -> None:
    """A guard that cannot fail reports nothing. Prove this one can.

    Args:
        tmp_path: A scratch tree the sweep is pointed at.
    """
    planted = tmp_path / "doc.md"
    planted.write_text(f"Run {RETIRED_INVOCATIONS[0]}something.\n", encoding="utf-8")
    swept = _sweepable(tmp_path)
    assert planted in swept, "the planted file must be inside the sweep's scope"
    assert any(
        retired in planted.read_text(encoding="utf-8")
        for retired in RETIRED_INVOCATIONS
    ), "the planted citation must be one the sweep looks for"


# --- Retired symbols (Q.5b) -------------------------------------------------
#
# Written as literals ON PURPOSE, unlike RETIRED_INVOCATIONS above: each is a
# class, function or module name this remediation plan deleted outright, not
# a recipe token this file would otherwise self-cite by assembling. None of
# them is a word this guard's own prose would ever use in passing.

#: Symbols this plan deleted, built from the deletion inventory in
#: SCHEDULE.md and RESIDUE.md. A name reappearing - a fresh import, a new
#: reference, a redefinition - means a deletion this plan already made
#: regressed. Extend this tuple as further deletions are confirmed; never
#: shrink it to make a regression pass.
RETIRED_SYMBOLS: tuple[str, ...] = (
    "EventAggregator",
    "MockChatModel",
    "Provider.MOCK",
    "mock_api_base",
    "ThreadStateData",
    "concurrent_checkpointer",
    "desktop_record_process_is_live",
    "process_start_fingerprint",
)

#: Modules deleted wholesale, checked by PATH rather than by a name inside
#: them: `database/admin.py` was folded into `vaultspec-a2a migrate
#: --compact` and removed (S08), so the file itself reappearing is the
#: regression, independent of what it would contain.
RETIRED_MODULE_PATHS: tuple[str, ...] = ("src/vaultspec_a2a/database/admin.py",)

#: Migration scripts under `database/migrations/versions/` are immutable
#: historical records (see the `migration-revision-boilerplate` category in
#: `dev/audit/duplication-baseline.json`) and may legitimately describe, in
#: prose, a class that existed when they were written - 0016 names
#: `EventAggregator` this way, as the thing the column it adds used to live
#: on only. The retired-INVOCATION sweep above needs no such exclusion today
#: because none of its citations have ever landed in one; this sweep does.
_SYMBOL_SWEEP_EXCLUDED_PARTS: frozenset[str] = frozenset({"migrations"})


def test_no_retired_symbol_reappears() -> None:
    """A name this plan deleted must not come back under the same spelling."""
    repo_root = REPO_ROOT
    this_file = Path(__file__).resolve()
    swept = [
        path
        for path in _sweepable(repo_root)
        # This module carries every retired symbol as a literal (the data
        # list itself), so it would otherwise flag itself as having cited
        # what it is the one place allowed to name.
        if path.resolve() != this_file
        and not _SYMBOL_SWEEP_EXCLUDED_PARTS & set(path.relative_to(repo_root).parts)
    ]
    assert len(swept) > 50, (
        f"the sweep found only {len(swept)} files under {SWEPT_ROOTS}; a corpus "
        "this small means a renamed tree retired the guard rather than failing it"
    )
    offenders: dict[str, list[str]] = defaultdict(list)
    for path in swept:
        text = path.read_text(encoding="utf-8", errors="replace")
        for symbol in RETIRED_SYMBOLS:
            if symbol in text:
                offenders[str(path.relative_to(repo_root))].append(symbol)
    assert not offenders, "these cite a symbol this plan deleted:\n  " + "\n  ".join(
        f"{path}: {', '.join(names)}" for path, names in sorted(offenders.items())
    )


def test_no_retired_module_path_exists() -> None:
    """A module deleted wholesale must not reappear at its old path."""
    present = [
        relative
        for relative in RETIRED_MODULE_PATHS
        if (REPO_ROOT / relative).is_file()
    ]
    assert not present, f"these retired modules have reappeared: {present}"


def test_the_symbol_sweep_can_actually_fail(tmp_path: Path) -> None:
    """Prove the symbol sweep can fail, the same way the invocation sweep must."""
    planted = tmp_path / "revived.py"
    planted.write_text(
        f"from somewhere import {RETIRED_SYMBOLS[0]}\n", encoding="utf-8"
    )
    swept = _sweepable(tmp_path)
    assert planted in swept, "the planted file must be inside the sweep's scope"
    assert RETIRED_SYMBOLS[0] in planted.read_text(encoding="utf-8"), (
        "the planted citation must be one the sweep looks for"
    )
