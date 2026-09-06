"""Unit proofs for portable current authority-schema fingerprints."""

from __future__ import annotations

from ..write_authority_schema import (
    WRITE_AUTHORITY_CHECKS,
    write_authority_checks_match,
    write_authority_receipt_index_matches,
)


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
