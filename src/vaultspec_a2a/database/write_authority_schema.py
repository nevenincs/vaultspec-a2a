"""Current schema identity for durable thread write authority."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from ..thread import RECEIPT_ID_MAX_LENGTH
from ..thread.enums import ControlActionType

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "ACTION_TYPE_MAX_LENGTH",
    "CONTROL_ACTION_SQL_VALUES",
    "RUN_REVISION_NONNEGATIVE",
    "WRITER_GENERATION_POSITIVE",
    "WRITE_AUTHORITY_CHECKS",
    "WRITE_AUTHORITY_COLUMNS",
    "WRITE_AUTHORITY_RECEIPT_INDEX",
    "WRITE_AUTHORITY_RECEIPT_INDEX_COLUMNS",
    "WRITE_AUTHORITY_VIOLATION_PREDICATE",
    "named_checks_match",
    "normalize_schema_expression",
    "receipt_id_bounded",
    "write_authority_checks_match",
    "write_authority_receipt_index_matches",
]

#: Column width of every stored control-action type.
ACTION_TYPE_MAX_LENGTH = 32
#: The journal's action and the run writer's action admit one vocabulary.
CONTROL_ACTION_SQL_VALUES = ", ".join(
    repr(action.value) for action in ControlActionType
)
#: The column invariants of a stored ``RunWriteAuthority``, whichever table
#: holds one.
RUN_REVISION_NONNEGATIVE = "run_revision >= 0"
WRITER_GENERATION_POSITIVE = "writer_generation >= 1"


def receipt_id_bounded(column: str) -> str:
    """Return the CHECK predicate bounding one action-receipt-id column."""
    return (
        f"length(trim({column})) >= 1 AND length({column}) <= {RECEIPT_ID_MAX_LENGTH}"
    )


WRITE_AUTHORITY_COLUMNS = {
    "run_revision": "INTEGER",
    "writer_generation": "INTEGER",
    "writer_action_type": f"VARCHAR({ACTION_TYPE_MAX_LENGTH})",
    "writer_action_receipt_id": f"VARCHAR({RECEIPT_ID_MAX_LENGTH})",
}
WRITE_AUTHORITY_CHECKS = {
    "ck_threads_run_revision_nonnegative": RUN_REVISION_NONNEGATIVE,
    "ck_threads_writer_generation_positive": WRITER_GENERATION_POSITIVE,
    "ck_threads_writer_action_type_current": (
        f"writer_action_type IN ({CONTROL_ACTION_SQL_VALUES})"
    ),
    "ck_threads_writer_action_receipt_id_bounded": receipt_id_bounded(
        "writer_action_receipt_id"
    ),
}
#: Matches a ``threads`` row breaking any current write-authority CHECK, so a
#: store's rows are proven against the predicates rather than trusted to them.
#: Every authority column is NOT NULL, so the negation never meets an unknown.
WRITE_AUTHORITY_VIOLATION_PREDICATE = (
    "NOT ("
    + " AND ".join(f"({predicate})" for predicate in WRITE_AUTHORITY_CHECKS.values())
    + ")"
)
WRITE_AUTHORITY_RECEIPT_INDEX = "ux_threads_writer_action_receipt_id"
WRITE_AUTHORITY_RECEIPT_INDEX_COLUMNS = ("writer_action_receipt_id",)


def normalize_schema_expression(expression: str, *, dialect: str = "sqlite") -> str:
    """Return a stable SQL predicate fingerprint without changing literals."""
    normalized: list[str] = []
    quoted = False
    index = 0
    while index < len(expression):
        character = expression[index]
        if character == "'":
            normalized.append(character)
            if quoted and index + 1 < len(expression) and expression[index + 1] == "'":
                normalized.append("'")
                index += 2
                continue
            quoted = not quoted
        elif quoted:
            normalized.append(character)
        elif character not in ' \t\r\n`"[]':
            normalized.append(character.lower())
        index += 1
    result = "".join(normalized)
    if dialect == "postgresql":
        result = re.sub(
            r"::(?:charactervarying|text)(?:\[\])?",
            "",
            result,
        ).replace("btrim(", "trim(")
        # PostgreSQL renders a reflected ``trim(x)`` as ``TRIM(BOTH FROM x)``,
        # which the whitespace strip above leaves as ``trim(bothfrom``. Without
        # this fold the receipt-id predicate never matches its own definition,
        # and the migration guard then refuses every revision after the one
        # that introduced write authority - on PostgreSQL only, and only for a
        # store that already carries it, so a fresh database still reaches head
        # and an existing one can never leave it. ``LEADING`` and ``TRAILING``
        # are different predicates and are deliberately not folded in.
        result = result.replace("trim(bothfrom", "trim(")
        result = result.replace("=any", "in")
        result = result.replace("[", "").replace("]", "")
        result = result.replace("(", "").replace(")", "")
        result = result.replace("inarray", "in")
    return result


def named_checks_match(
    checks: Mapping[str, str],
    required: Mapping[str, str],
    *,
    dialect: str = "sqlite",
) -> bool:
    """Return whether every required named CHECK has its exact current predicate."""
    normalized = {
        name.lower(): normalize_schema_expression(predicate, dialect=dialect)
        for name, predicate in checks.items()
    }
    return all(
        normalized.get(name) == normalize_schema_expression(predicate, dialect=dialect)
        for name, predicate in required.items()
    )


def write_authority_checks_match(
    checks: Mapping[str, str], *, dialect: str = "sqlite"
) -> bool:
    """Return whether every write-authority CHECK has its exact current predicate."""
    return named_checks_match(checks, WRITE_AUTHORITY_CHECKS, dialect=dialect)


def write_authority_receipt_index_matches(
    indexes: Iterable[Mapping[str, object]],
) -> bool:
    """Return whether the named receipt index is unique over its exact column."""
    for index in indexes:
        if index.get("name") != WRITE_AUTHORITY_RECEIPT_INDEX:
            continue
        column_names = index.get("column_names")
        if not isinstance(column_names, (list, tuple)):
            return False
        columns = tuple(
            str(column) for column in cast("Iterable[object]", column_names)
        )
        return bool(index.get("unique")) and (
            columns == WRITE_AUTHORITY_RECEIPT_INDEX_COLUMNS
        )
    return False
