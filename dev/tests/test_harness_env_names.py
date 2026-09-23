"""The repository harness's environment names: prefixed, documented, and live.

The service's settings are held to ``.env.example`` by the control tests. The
tooling under ``dev/`` and the test harness read names of their own, which the
example documents in its development-harness section. These tests hold that
section equal, in both directions, to the names the code actually reads.
"""

from __future__ import annotations

import re
from pathlib import Path

from dev.ci_formats import REPORT_NAME_ENV, REPORTS_ENV
from dev.exit_codes import ALLOW_EMPTY_ENV, FIX_STRICT_ENV
from dev.init.contract import FORCE_ENV, JSON_ENV
from vaultspec_a2a.control.settings_base import field_env_names
from vaultspec_a2a.service_tests._provider_catalog_live import (
    LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON,
    LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON,
)
from vaultspec_a2a.testing.session_root import TestSessionSettings

REPO_ROOT = Path(__file__).resolve().parents[2]
_HEADING = "# Development harness\n"
_NAME = re.compile(r"\b(VAULTSPEC_[A-Z0-9_]+)\b")


def _harness_names() -> set[str]:
    session = {
        field_env_names(TestSessionSettings, field)[0]
        for field in TestSessionSettings.model_fields
    }
    return {
        REPORTS_ENV,
        REPORT_NAME_ENV,
        FIX_STRICT_ENV,
        ALLOW_EMPTY_ENV,
        JSON_ENV,
        FORCE_ENV,
        *LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON,
        *LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON,
        *session,
    }


def _documented_harness_names() -> set[str]:
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert _HEADING in text, "the development-harness section is missing"
    return set(_NAME.findall(text.split(_HEADING, 1)[1]))


def test_every_harness_name_carries_the_a2a_prefix() -> None:
    stray = sorted(n for n in _harness_names() if not n.startswith("VAULTSPEC_A2A_"))
    assert not stray, f"harness names outside the VAULTSPEC_A2A_ prefix: {stray}"


def test_every_harness_name_is_documented() -> None:
    missing = sorted(_harness_names() - _documented_harness_names())
    assert not missing, f"harness names missing from .env.example: {missing}"


def test_the_harness_section_names_only_what_the_harness_reads() -> None:
    dead = sorted(_documented_harness_names() - _harness_names())
    assert not dead, f".env.example documents harness names nothing reads: {dead}"
