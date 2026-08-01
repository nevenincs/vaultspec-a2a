"""Promote the web sources a researcher turn cites into typed web locators.

The finding contract's ``locators`` list is the run's only typed evidence
channel, and the branch-side validation in :mod:`.nodes.diverge` enforces its
shape strictly: required ``kind``/``url``/``retrieved_at``, optional ``title``
and ``excerpt``, closed key set, hard character caps, and only ``http``/``https``
URLs. This module is the production emitter for that channel - the research
producer's bridge from what a researcher actually wrote to what the contract
admits.

**The producer normalises; the branch never has to refuse.** Branch-side
validation raises out of the researcher node, which carries no retry policy, so
a malformed locator would abort the whole run with no route into the revision
loop - and a retry could not help, the failure being deterministic. The
resolution is to make that raise unreachable from the production path: every
locator this module emits is contract-conformant by construction, so the
branch-side checks remain the guard for any other (injected, future) producer
rather than a trap the researcher can spring.

Normalisation is class-specific, because the malformations need different
operations and one blanket rule would be wrong for at least one of them:

- **Over-cap ``excerpt``** - truncated here with an elision marker. The producer
  is the party that knows which part of a retrieval carries the claim, which is
  exactly why the validator refuses rather than silently shortening.
- **Scheme-less host** (a bare ``domain/path``, the likelier malformation in
  practice) - NOT promoted, and never prefixed with a guessed scheme. ``http``
  and ``https`` are different origins with different security properties;
  inventing one fabricates a retrieval the run never made. An unpromoted URL
  costs only a weaker disclosure obligation, whereas an invented one puts a
  false claim into checkpointed state as evidence.
- **Over-cap ``url``** - NOT promoted. A truncated URL is a different URL: it
  would disclose a resource nobody retrieved.
- **More distinct URLs than the per-finding cap** - the first are kept in
  first-seen order. The cap matches the per-branch fetch budget, so a turn
  citing more sources than it could have fetched is citing recall past that
  point.

What this cannot distinguish is a URL the turn retrieved from one it recalled;
both reach the prose the same way, and provider-native web tools return their
results inside the model turn rather than as inspectable tool output. The
``retrieved_at`` stamp is therefore the turn's own completion instant - honest
about when the source entered the run, at the granularity a Sources section
cites at - and the persona honesty mandate governs the difference.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .nodes.diverge import (
    MAX_WEB_LOCATOR_EXCERPT_CHARS,
    MAX_WEB_LOCATOR_URL_CHARS,
    MAX_WEB_LOCATORS_PER_FINDING,
    WEB_LOCATOR_KIND,
)

__all__ = ["extract_web_locators"]

#: An absolute ``http(s)`` URL in prose. Anchored on the scheme deliberately: a
#: scheme-less host does not match and is therefore never promoted, which is the
#: normalisation decision for that class expressed in the pattern itself. The
#: terminating class stops at whitespace and at the closers that wrap a URL in
#: prose - autolink angle brackets, quotes, brackets - but NOT at ``)``, which is
#: resolved by balance in :func:`_trim_url` because it is both a markdown link's
#: closer and a legitimate URL character.
_PROSE_URL_RE = re.compile(r"https?://[^\s<>\"'`\[\]{}]+", re.IGNORECASE)

#: Sentence punctuation that a cited URL commonly abuts and that is never part of
#: the URL itself. Stripped from the tail only.
_URL_TRAILING_PUNCTUATION = ".,;:!?"


def _trim_url(candidate: str) -> str:
    """Strip the prose punctuation a cited URL abuts, and nothing else.

    A trailing ``)`` is dropped only when it closes something the URL never
    opened - the markdown link or parenthetical the citation sits inside. A
    balanced pair is kept, because a URL is not a prefix of itself: shortening
    ``.../Send_(disambiguation)`` would disclose a different resource, which is
    the same reason an over-cap URL is dropped rather than truncated.
    """
    url = candidate.rstrip(_URL_TRAILING_PUNCTUATION)
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1].rstrip(_URL_TRAILING_PUNCTUATION)
    return url


#: Appended to an elided excerpt so a reader can see the tail was dropped rather
#: than the source having said only this much.
_EXCERPT_ELISION = "…"


def _excerpt_for(line: str) -> str:
    """Return the citing line as a capped, whitespace-normalised excerpt.

    Whitespace is collapsed because the excerpt is checkpointed on every
    subsequent write and re-read by a human beside the URL; the shape of the
    researcher's line wrapping is not evidence. Over-cap text is truncated here,
    with the elision marked, so the shortening is the producer's deliberate act.
    """
    text = " ".join(line.split())
    if len(text) <= MAX_WEB_LOCATOR_EXCERPT_CHARS:
        return text
    head = text[: MAX_WEB_LOCATOR_EXCERPT_CHARS - len(_EXCERPT_ELISION)].rstrip()
    return f"{head}{_EXCERPT_ELISION}"


def extract_web_locators(prose: str, *, retrieved_at: str) -> list[dict[str, Any]]:
    """Extract contract-conformant web locators from a researcher turn's prose.

    *retrieved_at* is stamped once per turn by the caller and shared by every
    locator the turn yields: the retrieval and the turn are the same event at the
    granularity the citation channel discloses.

    Returns locators in first-seen order with duplicate URLs collapsed, so a
    replayed turn yields byte-identical evidence. Every returned locator
    satisfies the branch-side validation; anything that could not be made to
    satisfy it is omitted rather than repaired by guesswork.
    """
    locators: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in prose.splitlines():
        for match in _PROSE_URL_RE.finditer(line):
            url = _trim_url(match.group(0))
            if len(url) > MAX_WEB_LOCATOR_URL_CHARS or url in seen:
                continue
            if not urlsplit(url).netloc:
                # Scheme with nothing behind it: trimming ate the whole host, so
                # there is no origin to disclose. Same rule as a scheme-less host
                # - the channel takes a retrievable origin or nothing.
                continue
            seen.add(url)
            locator: dict[str, Any] = {
                "kind": WEB_LOCATOR_KIND,
                "url": url,
                "retrieved_at": retrieved_at,
            }
            # Unconditional: the line yielded a URL, so it collapses to a
            # non-empty excerpt by construction. A guard here would be one that
            # nothing can trigger, which is documentation wearing a check's
            # clothes.
            locator["excerpt"] = _excerpt_for(line)
            locators.append(locator)
            if len(locators) == MAX_WEB_LOCATORS_PER_FINDING:
                return locators
    return locators
