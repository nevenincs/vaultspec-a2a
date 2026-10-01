"""A proposal is refused for the leftovers and status forms vaultspec-core reports.

Core reports leftover template annotations, unreplaced template placeholders
and a malformed ADR status after a document lands; the submitter refuses the
same document before it is written. Each document here is written into a real
vault on disk and checked by core the way ``vault check`` checks a vault, and
the submitter's notes for the same text must be those diagnostics, word for
word. A writer is then never sent back for a leftover core accepts, nor waved
through with one core will report.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from vaultspec_core.graph import VaultGraph
from vaultspec_core.vaultcore.checks import (
    check_adr_status,
    check_annotations,
    check_placeholders,
)

from ..submitter import _conformance_notes

if TYPE_CHECKING:
    from pathlib import Path

_FRONTMATTER = (
    "---\ntags:\n  - '#{type}'\n  - '#document-checks'\ndate: '2026-10-01'\n---\n\n"
)

_ADR_H1 = "# `document-checks` adr: `probe` | (**status:** `accepted`)\n\n"

#: Bodies that exercise every leftover and status form the two sides could
#: read differently: the wider placeholder vocabulary, an enum choice, a
#: placeholder quoted as code, comments, and status sections real or quoted.
_BODIES = {
    "summary-placeholder": (
        "## Problem Statement\n\n{summary} of the {feature} at {tier}.\n"
    ),
    "step-placeholder": "## Problem Statement\n\nSee step {step_id} and {phase}.\n",
    "enum-choice": "## Problem Statement\n\nStatus is {proposed|accepted}.\n",
    "quoted-placeholder": (
        "## Problem Statement\n\nThe template writes `{title}` here.\n"
    ),
    "fenced-placeholder": "## Problem Statement\n\n```\n{topic}\n```\n",
    "annotation": "## Problem Statement\n\n<!-- template guidance -->\nBody.\n",
    "fenced-annotation": "## Problem Statement\n\n```html\n<!-- sample -->\n```\n",
    "legacy-status": "## Status\n\naccepted\n\n## Problem Statement\n\nBody.\n",
    "quoted-legacy-status": (
        "## Problem Statement\n\n```markdown\n## Status\n\naccepted\n```\n"
    ),
    "clean": "## Problem Statement\n\nBody.\n",
}

_H1_VARIANTS = {
    "canonical": _ADR_H1,
    "no-status": "# `document-checks` adr: `probe`\n\n",
    "unquoted": "# `document-checks` adr: `probe` | (**status:** accepted)\n\n",
    "off-vocabulary": "# `document-checks` adr: `probe` | (**status:** `draft`)\n\n",
}

#: The message prefixes of the three checks under test; the submitter's other
#: notes (frontmatter, body links, web disclosure) have their own coverage.
_PREFIXES = (
    "Template annotations remain",
    "Unreplaced template",
    "Unresolved template",
    "ADR ",
)


def _documents() -> dict[tuple[str, str], str]:
    documents: dict[tuple[str, str], str] = {}
    for name, body in _BODIES.items():
        documents[("research", name)] = (
            _FRONTMATTER.format(type="research") + "# probe\n\n" + body
        )
        for variant, h1 in _H1_VARIANTS.items():
            documents[("adr", f"{name}-{variant}")] = (
                _FRONTMATTER.format(type="adr") + h1 + body
            )
    return documents


def _relevant(notes: list[str]) -> list[str]:
    return sorted(note for note in notes if note.startswith(_PREFIXES))


def test_the_submitter_reports_what_core_reports_in_core_words(tmp_path: Path) -> None:
    documents = _documents()
    paths: dict[str, tuple[str, str]] = {}
    for index, ((doc_type, name), text) in enumerate(sorted(documents.items())):
        directory = tmp_path / ".vault" / doc_type
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"2026-10-01-document-checks-{index:03d}-{doc_type}.md"
        path.write_text(text, encoding="utf-8")
        paths[path.name] = (doc_type, name)

    graph = VaultGraph(tmp_path)
    graph.ensure_raw_texts()
    snapshot = graph.to_snapshot()
    results = [
        check_annotations(tmp_path, raw_texts=graph.raw_texts),
        check_placeholders(tmp_path, snapshot=snapshot),
        check_adr_status(tmp_path, snapshot=snapshot),
    ]
    core_notes: dict[str, list[str]] = defaultdict(list)
    for result in results:
        for diagnostic in result.diagnostics:
            assert diagnostic.path is not None
            core_notes[diagnostic.path.name].append(diagnostic.message)

    disagreements: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
    for file_name, key in paths.items():
        doc_type, _name = key
        expected = _relevant(core_notes[file_name])
        actual = _relevant(_conformance_notes(documents[key], doc_type))
        if expected != actual:
            disagreements[key] = (expected, actual)

    assert any(core_notes.values()), (
        "core reported nothing, so the corpus proves nothing"
    )
    assert not disagreements, next(iter(disagreements.items()))
