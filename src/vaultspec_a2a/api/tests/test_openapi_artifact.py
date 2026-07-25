"""The committed OpenAPI contract must match the application it documents.

Nothing validated this artifact before, and it drifted badly: it described 18
paths against the application's 24, omitting the whole versioned surface
(`/v1/runs` and its members, `/v1/presets`, `/v1/service`). Anything generated
from it - a typed client, most obviously - would have come out with no gateway
verbs at all, and the omission was invisible because the only test that touched
OpenAPI built the document live and never read the file.

It had also been written as cp1252 rather than UTF-8, which makes it invalid
JSON under RFC 8259, and it still carried architecture-record references that
the source no longer contains.

These assertions bind the file to the live application so the three cannot
recur silently.
"""

from __future__ import annotations

import json
import pathlib
import re

from ..app import create_app

_ARTIFACT = pathlib.Path(__file__).resolve().parents[3].parent / "openapi.json"
_REGENERATE_COMMAND = (
    "uv run --no-sync python -m vaultspec_a2a.api.tests.test_openapi_artifact"
)


def _live() -> dict:
    return create_app().openapi()


def _committed_bytes() -> bytes:
    return _ARTIFACT.read_bytes()


def _regenerate_artifact() -> None:
    """Rewrite the committed artifact from the live application, as UTF-8.

    This is the artifact's one regeneration path, named in every assertion
    failure below so a developer has a single, exact command to run rather
    than a description of what changed.
    """
    serialized = json.dumps(_live(), indent=2, ensure_ascii=False) + "\n"
    # newline="" disables the platform-default translation that would
    # otherwise widen every "\n" to "\r\n" on Windows; the committed file
    # uses LF-only line endings and must stay that way regardless of host.
    _ARTIFACT.write_text(serialized, encoding="utf-8", newline="")


if __name__ == "__main__":
    _regenerate_artifact()


def test_the_committed_artifact_is_valid_utf8_json() -> None:
    """A non-UTF-8 byte makes the file unreadable to a conforming parser.

    Decoded explicitly rather than via a helper: the failure being guarded is an
    encoding failure, so the decode itself is the assertion.
    """
    raw = _committed_bytes()
    decoded = raw.decode("utf-8")
    assert json.loads(decoded)["openapi"].startswith("3."), "not an OpenAPI document"


def test_the_committed_artifact_documents_every_live_path() -> None:
    """Every route the application serves appears in the published contract.

    This is the assertion the drift actually needed. Checking only that the file
    parses, or that it is non-empty, would have passed throughout the period it
    was missing the entire versioned surface.
    """
    live_paths = set(_live().get("paths", {}))
    committed_paths = set(json.loads(_committed_bytes().decode("utf-8"))["paths"])

    missing = sorted(live_paths - committed_paths)
    assert not missing, (
        f"openapi.json is missing {len(missing)} live path(s): {missing}. "
        f"Regenerate it: {_REGENERATE_COMMAND}"
    )


def test_the_committed_artifact_documents_no_path_the_app_does_not_serve() -> None:
    """The contract must not promise routes that no longer exist."""
    live_paths = set(_live().get("paths", {}))
    committed_paths = set(json.loads(_committed_bytes().decode("utf-8"))["paths"])

    stale = sorted(committed_paths - live_paths)
    assert not stale, (
        f"openapi.json documents {len(stale)} path(s) the app does not serve: "
        f"{stale}. Regenerate it: {_REGENERATE_COMMAND}"
    )


def test_the_committed_artifact_reports_the_running_version() -> None:
    """A stale version string misidentifies the contract a consumer generated from."""
    committed = json.loads(_committed_bytes().decode("utf-8"))
    assert committed["info"]["version"] == _live()["info"]["version"], (
        f"openapi.json reports a stale version. Regenerate it: {_REGENERATE_COMMAND}"
    )


def test_the_committed_artifact_matches_the_live_document_exactly() -> None:
    """The published contract must equal the live document field for field.

    Path-set and version checks alone would pass if a route's parameters,
    response schema, or description drifted from what the application
    actually serves - exactly the kind of drift a typed client generated from
    this file would silently encode. Compare the full parsed documents, and
    on mismatch narrow to the differing top-level and, for `paths`, per-route
    keys so a failure is diagnosable without a manual diff.
    """
    live = _live()
    committed = json.loads(_committed_bytes().decode("utf-8"))
    if live == committed:
        return

    top_level_diffs = sorted(
        key for key in set(live) | set(committed) if live.get(key) != committed.get(key)
    )
    path_diffs = sorted(
        route
        for route in set(live.get("paths", {})) | set(committed.get("paths", {}))
        if live.get("paths", {}).get(route) != committed.get("paths", {}).get(route)
    )
    raise AssertionError(
        "openapi.json does not match create_app().openapi(): "
        f"differing top-level key(s) {top_level_diffs}, differing route(s) "
        f"{path_diffs}. Regenerate it: {_REGENERATE_COMMAND}"
    )


def test_the_published_contract_carries_no_development_record_references() -> None:
    """Vault identifiers must not reach a published artifact.

    Development records cite code; code never cites them, and a published
    contract is the furthest thing from a development record. The source tree
    was scrubbed of these, but this artifact predated the scrub and kept them.
    """
    text = _committed_bytes().decode("utf-8")
    leaked = re.findall(r"ADR-\d{3}", text)
    assert not leaked, (
        f"published contract references development records: {leaked}. "
        f"Regenerate it: {_REGENERATE_COMMAND}"
    )
