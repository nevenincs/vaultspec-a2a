"""The submitter reads body prose exactly as vaultspec-core does.

Core refuses a body link after a document lands and the submitter refuses it
before the document is written. If the two disagree about what is prose, a
writer is sent back to revise a document core would accept, or a document
core will reject is let through. Agreement is checked against the installed
core, not against a copy of its expectations, so a core upgrade that changes
its reader fails here on the day the lock is bumped.
"""

from __future__ import annotations

import random

import pytest
from vaultspec_core.vaultcore.links import strip_non_prose as core_strip_non_prose
from vaultspec_core.vaultcore.links import wiki_links_from_prose

from .._prose import strip_non_prose
from ..submitter import _MD_LINK_RE, _conformance_notes

_FRONTMATTER = "---\ntags:\n  - '#research'\n  - '#prose-parity'\n---\n"

#: Markdown-significant fragments: every construct the reader distinguishes,
#: the links it must hide or expose, and the whitespace that moves margins.
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
    "\r\n",
    " ",
    "   ",
    "    ",
    "\t",
    "- ",
    "1. ",
    "* ",
    "[[x]]",
    "[[y|z]]",
    "[a](b.md)",
    "[c](https://e.org)",
    "word",
    "#",
)

_NAMED_CASES = {
    "double-backtick span quoting a link": "see ``[[x]]`` here",
    "double-backtick span holding a backtick": "a `` ` [[x]] `` b [[y]]",
    "unequal runs do not close": "a ``[[x]]` b",
    "fence nested in a list item": "- item\n\n  ```\n  [[x]]\n  ```\n[[y]]",
    "unclosed fence runs to the end": "text\n```\n[[x]]\n",
    "longer closing run closes": "````\n[[x]]\n``````\n[[y]]",
    "shorter closing run does not close": "````\n[[x]]\n```\n[[y]]",
    "code span cannot cross into a fence": "a `x\n```\n[[x]]\n```\nb` [[y]]",
    "comment hides a fence marker": "<!-- ```\n[[x]] -->\n[[y]]",
    "code span hides a comment marker": "`<!--` [[x]] `-->`",
    "indented fence is not a fence": "    ```\n[[x]]",
    "tilde fence": "~~~ info\n[[x]]\n~~~\n[a](b.md)",
    "backtick info string with a backtick": "``` a`b\n[[x]]\n```",
}


def _submitter_link_counts(prose: str) -> tuple[int, int]:
    notes = _conformance_notes(_FRONTMATTER + prose)
    return (
        sum(note.startswith("wiki-link in body text") for note in notes),
        sum(note.startswith("markdown link in body text") for note in notes),
    )


def _core_link_counts(prose: str) -> tuple[int, int]:
    stripped = core_strip_non_prose(prose)
    return (
        sum(wiki_links_from_prose(stripped).values()),
        len(_MD_LINK_RE.findall(stripped)),
    )


def _generated_bodies(count: int) -> list[str]:
    rng = random.Random(20261001)
    return [
        "".join(rng.choice(_FRAGMENTS) for _ in range(rng.randint(3, 40)))
        for _ in range(count)
    ]


@pytest.mark.parametrize("prose", _NAMED_CASES.values(), ids=_NAMED_CASES.keys())
def test_named_constructs_strip_as_core_strips(prose: str) -> None:
    assert strip_non_prose(prose) == core_strip_non_prose(prose)


@pytest.mark.parametrize("prose", _NAMED_CASES.values(), ids=_NAMED_CASES.keys())
def test_submitter_flags_the_links_core_flags(prose: str) -> None:
    assert _submitter_link_counts(prose) == _core_link_counts(prose)


def test_generated_bodies_strip_as_core_strips() -> None:
    disagreements = [
        prose
        for prose in _generated_bodies(3000)
        if strip_non_prose(prose) != core_strip_non_prose(prose)
    ]
    assert not disagreements, f"first disagreement: {disagreements[0]!r}"


def test_generated_bodies_flag_the_links_core_flags() -> None:
    disagreements = [
        prose
        for prose in _generated_bodies(3000)
        if _submitter_link_counts(prose) != _core_link_counts(prose)
    ]
    assert not disagreements, f"first disagreement: {disagreements[0]!r}"
