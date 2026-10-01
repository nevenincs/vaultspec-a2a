"""The prose of a vault document body: everything that is not code or a comment.

vaultspec-core refuses a body link after a document lands, and the submitter
refuses the same link before it is written. The two must agree on which text
is prose, so this is a port of core's reader (``vaultcore/markdown.py``,
``non_prose_spans``) rather than an approximation of it, and a parity test
holds it to the installed core.

The rules are the CommonMark subset a line scanner can apply:

- A fence opens on a line indented at most three spaces past the current
  margin with a run of three or more backticks or tildes; a backtick fence's
  info string may not contain a backtick. It closes on a run of the same
  character at least as long, followed only by whitespace. An unclosed fence
  runs to the end of the text.
- A list item moves the margin those three spaces are counted from, so a
  fence nested in a list item is a fence however deep the nesting.
- An inline code span is a backtick run, its content, and a closing run of
  the same length, so a double-backtick span may quote a single backtick. A
  span cannot cross a block: one that would reach a fence's opening line is
  literal text.
- An HTML comment hides everything up to its first ``-->``, and a line that
  begins inside one carries no structure.

Whichever construct begins first wins.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["non_prose_spans", "strip_non_prose"]

_HTML_COMMENT_RE = re.compile(r"<!--(?:-?>|.*?-->)", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1", re.DOTALL)
_COMMENT_OR_CODE_RE = re.compile(
    rf"{_HTML_COMMENT_RE.pattern}|{_INLINE_CODE_RE.pattern}", re.DOTALL
)
_LINE_WHITESPACE = " \t\r\n"
_FENCE_RE = re.compile(r" {0,3}(?P<run>`{3,}|~{3,})(?P<rest>.*)")
_LIST_ITEM_RE = re.compile(r"(?P<marker>[-+*]|\d{1,9}[.)])(?:(?P<gap>[ \t]+).*)?")
_LIST_GAP_LIMIT = 4

_TEXT = "text"
_FENCE_OPEN = "fence-open"
_CODE = "code"
_FENCE_CLOSE = "fence-close"


class _FenceTracker:
    """Classify lines one at a time, carrying the open fence and list margins."""

    __slots__ = ("_char", "_items", "_length", "_margin")

    def __init__(self) -> None:
        self._char = ""
        self._length = 0
        self._margin = 0
        self._items: list[int] = []

    def classify(self, line: str) -> str:
        indent = len(line) - len(line.lstrip(" "))
        if self._char:
            return self._close_or_code(line, indent)
        if not line.strip(_LINE_WHITESPACE):
            return _TEXT
        while self._items and self._items[-1] > indent:
            self._items.pop()
        margin = self._items[-1] if self._items else 0
        match = _FENCE_RE.match(line, margin)
        if match is not None:
            run = match.group("run")
            if run[0] != "`" or "`" not in match.group("rest"):
                self._char, self._length, self._margin = run[0], len(run), margin
                return _FENCE_OPEN
        if indent - margin <= 3:
            self._open_item(line, indent)
        return _TEXT

    def _close_or_code(self, line: str, indent: int) -> str:
        match = _FENCE_RE.match(line, min(indent, self._margin))
        if (
            match is not None
            and match.group("run")[0] == self._char
            and len(match.group("run")) >= self._length
            and not match.group("rest").strip(_LINE_WHITESPACE)
        ):
            self._char, self._length, self._margin = "", 0, 0
            return _FENCE_CLOSE
        return _CODE

    def _open_item(self, line: str, indent: int) -> None:
        item = _LIST_ITEM_RE.fullmatch(line.rstrip(_LINE_WHITESPACE), indent)
        if item is None:
            return
        gap = len(item.group("gap") or "")
        width = gap if 0 < gap <= _LIST_GAP_LIMIT else 1
        self._items.append(indent + len(item.group("marker")) + width)


def non_prose_spans(text: str) -> list[tuple[int, int]]:
    """Return the ``(start, end)`` spans of *text* that are code or comments.

    Args:
        text: Markdown text; lines are split on ``\\n``.

    Returns:
        The spans in order, never overlapping.
    """
    lines = text.split("\n")
    starts = _line_starts(lines)
    tracker = _FenceTracker()
    spans: list[tuple[int, int]] = []
    # The end of the last comment or fence: a line starting before it is
    # comment text, never structure.
    cursor = 0
    fence_start: int | None = None
    match = _COMMENT_OR_CODE_RE.search(text)
    for index, line in enumerate(lines):
        start = starts[index]
        if fence_start is not None:
            if tracker.classify(line) == _FENCE_CLOSE:
                cursor = start + len(line)
                spans.append((fence_start, cursor))
                fence_start = None
                if match is None or match.start() < cursor:
                    match = _COMMENT_OR_CODE_RE.search(text, cursor)
            continue
        while match is not None and match.start() < start:
            is_code = match.group(1) is not None
            if is_code and match.end() > start:
                break
            spans.append(match.span())
            if not is_code:
                cursor = match.end()
            match = _COMMENT_OR_CODE_RE.search(text, match.end())
        if start < cursor:
            continue
        if tracker.classify(line) == _FENCE_OPEN:
            fence_start = start
            if match is not None and match.start() < start:
                # A code span reaching this fence's line is a stray backtick
                # run; only the constructs wholly before the fence are kept.
                spans.extend(_inline_spans(text, match.end(1), start - 1))
                match = None
    if fence_start is not None:
        spans.append((fence_start, len(text)))
        match = None
    while match is not None:
        spans.append(match.span())
        match = _COMMENT_OR_CODE_RE.search(text, match.end())
    return spans


def strip_non_prose(text: str) -> str:
    """Return *text* without its code blocks, code spans, and HTML comments."""
    parts: list[str] = []
    cursor = 0
    for start, end in non_prose_spans(text):
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _inline_spans(text: str, pos: int, endpos: int) -> Iterator[tuple[int, int]]:
    match = _COMMENT_OR_CODE_RE.search(text, pos, endpos)
    while match is not None:
        yield match.span()
        match = _COMMENT_OR_CODE_RE.search(text, match.end(), endpos)


def _line_starts(lines: list[str]) -> list[int]:
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    return starts
