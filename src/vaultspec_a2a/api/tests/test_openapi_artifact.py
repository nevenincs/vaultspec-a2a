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


def _live() -> dict:
    return create_app().openapi()


def _committed_bytes() -> bytes:
    return _ARTIFACT.read_bytes()


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
        "Regenerate it from create_app().openapi()."
    )


def test_the_committed_artifact_documents_no_path_the_app_does_not_serve() -> None:
    """The contract must not promise routes that no longer exist."""
    live_paths = set(_live().get("paths", {}))
    committed_paths = set(json.loads(_committed_bytes().decode("utf-8"))["paths"])

    stale = sorted(committed_paths - live_paths)
    assert not stale, (
        f"openapi.json documents {len(stale)} path(s) the app does not serve: "
        f"{stale}. Regenerate it from create_app().openapi()."
    )


def test_the_committed_artifact_reports_the_running_version() -> None:
    """A stale version string misidentifies the contract a consumer generated from."""
    committed = json.loads(_committed_bytes().decode("utf-8"))
    assert committed["info"]["version"] == _live()["info"]["version"]


def test_the_published_contract_carries_no_development_record_references() -> None:
    """Vault identifiers must not reach a published artifact.

    Development records cite code; code never cites them, and a published
    contract is the furthest thing from a development record. The source tree
    was scrubbed of these, but this artifact predated the scrub and kept them.
    """
    text = _committed_bytes().decode("utf-8")
    leaked = re.findall(r"ADR-\d{3}", text)
    assert not leaked, f"published contract references development records: {leaked}"
