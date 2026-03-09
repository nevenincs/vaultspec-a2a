"""Repo hygiene checks for checked-in env and compose files."""

from __future__ import annotations

import re

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[3]
_FILES = [
    _ROOT / ".env.example",
    _ROOT / ".env.integration.example",
    _ROOT / "docker-compose.dev.yml",
    _ROOT / "docker-compose.integration.yml",
    _ROOT / "docker-compose.prod.yml",
]
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{12,}"),
    re.compile(r"lsv2_[A-Za-z0-9_]{12,}"),
    re.compile(r"hf_[A-Za-z0-9]{12,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{12,}"),
    re.compile(r"figd_[0-9A-Za-z_-]{12,}"),
]


def test_checked_in_compose_and_env_files_do_not_contain_live_tokens() -> None:
    """Checked-in templates should not contain obvious live credential strings."""
    for path in _FILES:
        text = path.read_text(encoding="utf-8")
        for pattern in _SECRET_PATTERNS:
            assert pattern.search(text) is None, f"possible secret found in {path}"
