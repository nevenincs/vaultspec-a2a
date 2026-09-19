"""Current schema identity for durable thread write authority."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from ..thread.enums import ControlActionType

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


def _skip_quoted(sql: str, cursor: int, opener: str) -> tuple[int, bool]:
    """Skip one SQL string or quoted identifier, honoring doubled closers."""
    closer = "]" if opener == "[" else opener
    cursor += 1
    while cursor < len(sql):
        if sql[cursor] != closer:
            cursor += 1
            continue
        if closer != "]" and cursor + 1 < len(sql) and sql[cursor + 1] == closer:
            cursor += 2
            continue
        return cursor + 1, True
    return len(sql), False


def _skip_space_and_comments(sql: str, cursor: int) -> tuple[int, bool]:
    """Skip SQL trivia and report an unterminated block comment."""
    while cursor < len(sql):
        if sql[cursor].isspace():
            cursor += 1
        elif sql.startswith("--", cursor):
            newline = sql.find("\n", cursor + 2)
            cursor = len(sql) if newline < 0 else newline + 1
        elif sql.startswith("/*", cursor):
            end = sql.find("*/", cursor + 2)
            if end < 0:
                return len(sql), False
            cursor = end + 2
        else:
            break
    return cursor, True


def _read_identifier(sql: str, cursor: int) -> tuple[str | None, int, bool]:
    """Read one bare or SQLite-quoted identifier."""
    if cursor >= len(sql):
        return None, cursor, True
    if sql[cursor] in ('"', "`", "["):
        opener = sql[cursor]
        end, valid = _skip_quoted(sql, cursor, opener)
        if not valid:
            return None, end, False
        closer_width = 1
        raw = sql[cursor + 1 : end - closer_width]
        closer = "]" if opener == "[" else opener
        if closer != "]":
            raw = raw.replace(closer * 2, closer)
        return raw, end, True
    end = cursor
    while end < len(sql) and (sql[end].isalnum() or sql[end] in "_$"):
        end += 1
    if end == cursor:
        return None, cursor, True
    return sql[cursor:end], end, True


def _read_check_body(sql: str, cursor: int) -> tuple[str, int, bool]:
    """Read one balanced CHECK predicate, preserving its original SQL text."""
    depth = 1
    cursor += 1
    start = cursor
    while cursor < len(sql) and depth:
        character = sql[cursor]
        if sql.startswith(("--", "/*"), cursor):
            cursor, valid = _skip_space_and_comments(sql, cursor)
            if not valid:
                return "", cursor, False
            continue
        if character in ("'", '"', "`", "["):
            cursor, valid = _skip_quoted(sql, cursor, character)
            if not valid:
                return "", cursor, False
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        cursor += 1
    return sql[start : cursor - 1], cursor, depth == 0


def _read_named_check(sql: str, cursor: int) -> tuple[str | None, str, int, bool]:
    """Read the name and predicate following a CONSTRAINT token."""
    cursor, valid = _skip_space_and_comments(sql, cursor)
    name, cursor, identifier_valid = _read_identifier(sql, cursor)
    if not valid or not identifier_valid or name is None:
        return None, "", cursor, False
    cursor, valid = _skip_space_and_comments(sql, cursor)
    check_word, cursor, identifier_valid = _read_identifier(sql, cursor)
    if not valid or not identifier_valid:
        return None, "", cursor, False
    if check_word is None or check_word.lower() != "check":
        return None, "", cursor, True
    cursor, valid = _skip_space_and_comments(sql, cursor)
    if not valid or cursor >= len(sql):
        return None, "", cursor, False
    if sql[cursor] != "(":
        return None, "", cursor, True
    body, cursor, valid = _read_check_body(sql, cursor)
    return name.lower(), body, cursor, valid


def _next_sql_word(sql: str, cursor: int) -> tuple[str | None, int, bool]:
    """Advance past trivia or quoted text and read the next bare identifier."""
    cursor, valid = _skip_space_and_comments(sql, cursor)
    if not valid or cursor >= len(sql):
        return None, cursor, valid
    if sql[cursor] in ("'", '"', "`", "["):
        cursor, valid = _skip_quoted(sql, cursor, sql[cursor])
        return None, cursor, valid
    word, after_word, valid = _read_identifier(sql, cursor)
    return word, after_word if word is not None else cursor + 1, valid


def extract_named_check_predicates(create_table_sql: str) -> dict[str, str]:
    """Extract real named SQLite CHECKs, ignoring comments and quoted content."""
    checks: dict[str, str] = {}
    cursor = 0
    while cursor < len(create_table_sql):
        word, cursor, valid = _next_sql_word(create_table_sql, cursor)
        if not valid:
            return {}
        if word is None or word.lower() != "constraint":
            continue
        name, predicate, cursor, valid = _read_named_check(create_table_sql, cursor)
        if not valid or (name is not None and name in checks):
            return {}
        if name is not None:
            checks[name] = predicate
    return checks


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
