"""The run-id grammar is declared twice and the two must never disagree.

One grammar decides which persisted rows a listing query returns - a SQL
predicate in the thread repository - and another decides whether a response
model will serialize, as a pattern on the wire schema's annotated identity type.
They are byte-identical today, and everything downstream quietly depends on that.

Why this needs a test rather than a comment. The two are consumed at DIFFERENT
ends of one request: the filter runs in the database, the pattern runs at
serialization. If the filter ever became the LOOSER of the two, rows would pass
it and then fail the response model, and a single legacy row would stop a whole
listing endpoint for every caller rather than failing its own run. That is not a
hypothetical shape - it is exactly the failure this pairing was introduced to
prevent, and it returns silently the moment the two definitions drift.

Sharing one declaration outright is not obviously right, which is the other
reason to test rather than merge. A Pydantic ``pattern`` is a string compiled by
pydantic-core; a SQLAlchemy ``regexp_match`` is dialect-dispatched to the
database's own engine. They are different regex implementations, so one shared
literal would still not guarantee identical MATCHING - it would only guarantee
identical TEXT. Testing the text is honest about exactly that much.

Read from source rather than by importing and inspecting. The SQL side wraps its
pattern inside a SQLAlchemy expression object, so recovering it at runtime means
reaching through library internals that are free to change; the literal in the
file is the thing an author edits and the thing that must agree.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

_SOURCE_ROOT = Path(__file__).resolve().parents[1]

# Matches a raw-string literal opening with the run-id grammar's anchor and
# character class, which is specific enough that no unrelated pattern in these
# two modules collides with it.
_GRAMMAR_LITERAL: Final = re.compile(r'r"(\^\[A-Za-z0-9_\]\[A-Za-z0-9_-\][^"]*)"')

_DECLARING_MODULES: Final = (
    "api/schemas/gateway.py",
    "database/thread_repository.py",
)


def _declared_grammars(module: str) -> list[str]:
    """Return every run-id grammar literal written in *module*'s source."""
    source = (_SOURCE_ROOT / module).read_text(encoding="utf-8")
    return [match.group(1) for match in _GRAMMAR_LITERAL.finditer(source)]


def test_the_wire_pattern_and_the_sql_filter_use_one_grammar() -> None:
    """The serialization pattern and the row filter must be the same string."""
    found = {module: _declared_grammars(module) for module in _DECLARING_MODULES}

    missing = [module for module, grammars in found.items() if not grammars]
    assert not missing, (
        f"No run-id grammar literal found in {missing}. Either it moved - in "
        "which case move this test with it - or a declaration was deleted, "
        "which is the more dangerous reading: the filter and the response "
        "pattern only protect each other while both exist."
    )

    distinct = {grammar for grammars in found.values() for grammar in grammars}
    assert len(distinct) == 1, (
        f"The run-id grammar disagrees between its declarations: {found}.\n\n"
        "One of these filters which persisted rows a listing returns; the other "
        "decides whether the response model serializes. If the FILTER is the "
        "looser of the two, a row passes it and then fails the model, and one "
        "malformed identity stops the entire listing endpoint for every caller "
        "instead of failing its own run.\n\n"
        "Change both, or neither."
    )
