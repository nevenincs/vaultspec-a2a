"""Current schema identity for durable thread write authority."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from ..thread.enums import ControlActionType
from ._write_authority_check_parser import (
    extract_named_check_predicates as extract_named_check_predicates,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

WRITE_AUTHORITY_COLUMNS = {
    "run_revision": "INTEGER",
    "writer_generation": "INTEGER",
    "writer_action_type": "VARCHAR(32)",
    "writer_action_receipt_id": "VARCHAR(64)",
}
WRITE_ACTION_TYPES = tuple(action.value for action in ControlActionType)
WRITE_ACTION_SQL_VALUES = ", ".join(repr(value) for value in WRITE_ACTION_TYPES)
WRITE_AUTHORITY_CHECKS = {
    "ck_threads_run_revision_nonnegative": "run_revision >= 0",
    "ck_threads_writer_generation_positive": "writer_generation >= 1",
    "ck_threads_writer_action_type_current": (
        f"writer_action_type IN ({WRITE_ACTION_SQL_VALUES})"
    ),
    "ck_threads_writer_action_receipt_id_bounded": (
        "length(trim(writer_action_receipt_id)) >= 1 "
        "AND length(writer_action_receipt_id) <= 64"
    ),
}
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
        result = result.replace("=any", "in")
        result = result.replace("[", "").replace("]", "")
        result = result.replace("(", "").replace(")", "")
        result = result.replace("inarray", "in")
    return result


def write_authority_checks_match(
    checks: Mapping[str, str], *, dialect: str = "sqlite"
) -> bool:
    """Return whether every required named CHECK has its exact current predicate."""
    normalized = {
        name.lower(): normalize_schema_expression(predicate, dialect=dialect)
        for name, predicate in checks.items()
    }
    return all(
        normalized.get(name) == normalize_schema_expression(predicate, dialect=dialect)
        for name, predicate in WRITE_AUTHORITY_CHECKS.items()
    )


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
