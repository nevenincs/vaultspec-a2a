"""Extract named SQLite CHECK predicates from CREATE TABLE SQL."""

from __future__ import annotations


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
    return _read_named_check_body(sql, cursor, name)


def _read_named_check_body(
    sql: str, cursor: int, name: str
) -> tuple[str | None, str, int, bool]:
    """Read the balanced predicate after a named CHECK keyword."""
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
