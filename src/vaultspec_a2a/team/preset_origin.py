"""Where a discovered team preset came from.

Its own module rather than an addition to ``team_config``: this vocabulary is
the answer to a DISCOVERY question - which of the searched locations produced
this preset - while ``team_config`` owns what a preset CONTAINS once loaded. The
two are read by different callers, and the preset listing needs this one without
parsing a single TOML file.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["PresetOrigin"]


class PresetOrigin(StrEnum):
    """Which source supplied a discovered preset.

    ``WORKSPACE`` outranks ``BUNDLED`` for the same id, because a workspace
    definition shadows the shipped one; the origin therefore reports where the
    preset a caller would actually get was found, not merely where a file
    exists. ``TEST_MOCK`` is a shipped preset that follows the mock naming
    convention, kept a separate member rather than folded into ``BUNDLED`` so
    the product layer can exclude fixtures without matching on the id.
    """

    BUNDLED = "bundled"
    WORKSPACE = "workspace"
    TEST_MOCK = "test_mock"
