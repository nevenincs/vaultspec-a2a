"""A proposal is refused for exactly the body links vaultspec-core refuses.

Core refuses a body link after a document lands and the submitter refuses it
before the document is written. Each document here is written into a real vault
on disk and checked by core the way ``vault check`` checks a vault: core's
graph reads the files and core's ``body-links`` check runs over them. The
submitter's revision notes for the same text must be those diagnostics, word
for word, so a writer is never sent back for a link core accepts nor waved
through with one core will reject.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import TYPE_CHECKING

from vaultspec_core.graph import VaultGraph
from vaultspec_core.vaultcore.checks import check_body_links

from ..submitter import _conformance_notes

if TYPE_CHECKING:
    from pathlib import Path

_FRONTMATTER = (
    "---\ntags:\n  - '#research'\n  - '#body-links'\ndate: '2026-10-01'\n---\n\n"
)

#: Markdown-significant fragments: every construct a prose reader must tell
#: apart, the links it must hide or expose, and the whitespace that moves margins.
_FRAGMENTS = (
    "`",
    "``",
    "```",
    "````",
    "~~~",
    "<!--",
    "-->",
    "\n",
    "\n\n",
    " ",
    "    ",
    "- ",
    "1. ",
    "[[x]]",
    "[[y|z]]",
    "[[w.md]]",
    "[a](b.md)",
    "[c](https://e.org)",
    "word",
)

_NAMED = (
    "see ``[[x]]`` here",
    "a `` ` [[x]] `` b [[y]]",
    "- item\n\n  ```\n  [[x]]\n  ```\n[[y]]",
    "text\n```\n[[x]]\n",
    "````\n[[x]]\n```\n[[y]]",
    "a `x\n```\n[[x]]\n```\nb` [[y]]",
    "<!-- ```\n[[x]] -->\n[[y]]",
    "`<!--` [[x]] `-->`",
    "~~~ info\n[[x]]\n~~~\n[a](b.md)",
    "[[ spaced ]] and [[note.md]]",
)


def _bodies() -> list[str]:
    rng = random.Random(20261001)
    generated = [
        "".join(rng.choice(_FRAGMENTS) for _ in range(rng.randint(3, 30)))
        for _ in range(300)
    ]
    return [*_NAMED, *generated]


def _link_notes(document: str) -> list[str]:
    return [
        note
        for note in _conformance_notes(document)
        if note.startswith(("Wiki-link in body text", "Markdown link in body text"))
    ]


def test_the_submitter_refuses_what_core_refuses_in_core_words(tmp_path: Path) -> None:
    research = tmp_path / ".vault" / "research"
    research.mkdir(parents=True)
    documents: dict[str, str] = {}
    for index, body in enumerate(_bodies()):
        name = f"2026-10-01-body-links-{index:03d}-research.md"
        documents[name] = f"{_FRONTMATTER}# probe {index}\n\n{body}\n"
        (research / name).write_text(documents[name], encoding="utf-8")

    result = check_body_links(tmp_path, snapshot=VaultGraph(tmp_path).to_snapshot())
    core_notes: dict[str, list[str]] = defaultdict(list)
    for diagnostic in result.diagnostics:
        assert diagnostic.path is not None
        core_notes[diagnostic.path.name].append(diagnostic.message)

    disagreements = {
        name: (core_notes[name], _link_notes(document))
        for name, document in documents.items()
        if sorted(core_notes[name]) != sorted(_link_notes(document))
    }
    assert core_notes, "core flagged nothing, so the corpus proves nothing"
    assert not disagreements, next(iter(disagreements.items()))
