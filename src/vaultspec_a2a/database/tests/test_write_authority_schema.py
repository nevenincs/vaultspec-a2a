"""Unit proofs for portable current authority-schema fingerprints."""

from __future__ import annotations

import pytest

from ..write_authority_schema import (
    WRITE_AUTHORITY_CHECKS,
    extract_named_check_predicates,
    write_authority_checks_match,
    write_authority_receipt_index_matches,
)


def _canonical_create_table(*, quote: str = "") -> str:
    close = "]" if quote == "[" else quote
    constraints = ", ".join(
        f"CONSTRAINT {quote}{name}{close} CHECK ({predicate})"
        for name, predicate in WRITE_AUTHORITY_CHECKS.items()
    )
    return f"CREATE TABLE threads (id TEXT, {constraints})"


@pytest.mark.parametrize("quote", ["", '"', "`", "["])
def test_sqlite_parser_accepts_canonical_checks_and_quoted_names(quote: str) -> None:
    checks = extract_named_check_predicates(_canonical_create_table(quote=quote))
    assert checks == WRITE_AUTHORITY_CHECKS
    assert write_authority_checks_match(checks)


@pytest.mark.parametrize(
    "carrier",
    [
        "/* CONSTRAINT authority CHECK (run_revision >= 0) */",
        "-- CONSTRAINT authority CHECK (run_revision >= 0)\n",
        "'CONSTRAINT authority CHECK (run_revision >= 0)'",
    ],
)
def test_sqlite_parser_ignores_required_text_outside_sql_code(carrier: str) -> None:
    sql = f"CREATE TABLE threads (id TEXT, {carrier})"
    assert extract_named_check_predicates(sql) == {}


@pytest.mark.parametrize(
    "malformed",
    [
        "CREATE TABLE threads (id TEXT /* unterminated",
        "CREATE TABLE threads (id TEXT, 'unterminated)",
        'CREATE TABLE threads (id TEXT, "unterminated)',
        "CREATE TABLE threads (id TEXT, CONSTRAINT authority CHECK (((id > 0))",
    ],
)
def test_sqlite_parser_fails_closed_on_unterminated_lexemes(malformed: str) -> None:
    assert extract_named_check_predicates(malformed) == {}


def test_sqlite_parser_fails_closed_on_duplicate_constraint_name() -> None:
    sql = (
        "CREATE TABLE threads (id TEXT, "
        "CONSTRAINT duplicated CHECK (id IS NOT NULL), "
        "CONSTRAINT duplicated CHECK (length(id) > 0))"
    )
    assert extract_named_check_predicates(sql) == {}


def test_sqlite_parser_retains_literals_inside_real_predicate() -> None:
    sql = "CREATE TABLE threads (CONSTRAINT named CHECK (kind IN ('a)', 'b''c')))"
    assert extract_named_check_predicates(sql) == {"named": "kind IN ('a)', 'b''c')"}


def test_same_named_permissive_check_does_not_match() -> None:
    forged = dict(WRITE_AUTHORITY_CHECKS)
    forged["ck_threads_run_revision_nonnegative"] = "1"
    assert not write_authority_checks_match(forged)


def test_same_named_wrong_column_index_does_not_match() -> None:
    assert not write_authority_receipt_index_matches(
        [
            {
                "name": "ux_threads_writer_action_receipt_id",
                "unique": True,
                "column_names": ["id"],
            }
        ]
    )


def test_postgresql_rendered_checks_normalize_to_current_predicates() -> None:
    rendered = dict(WRITE_AUTHORITY_CHECKS)
    rendered["ck_threads_writer_action_type_current"] = (
        "((writer_action_type)::text = ANY "
        "((ARRAY['ingest'::character varying, 'resume'::character varying, "
        "'cancel'::character varying, 'permission_request_created'::character "
        "varying, 'permission_response_submitted'::character varying, "
        "'permission_response_applied'::character varying, "
        "'message_followup_requested'::character varying, "
        "'message_followup_applied'::character varying, "
        "'repair_started'::character varying, "
        "'repair_finished'::character varying])::text[]))"
    )
    rendered["ck_threads_writer_action_receipt_id_bounded"] = (
        "((length(btrim((writer_action_receipt_id)::text)) >= 1) AND "
        "(length((writer_action_receipt_id)::text) <= 64))"
    )
    assert write_authority_checks_match(rendered, dialect="postgresql")
