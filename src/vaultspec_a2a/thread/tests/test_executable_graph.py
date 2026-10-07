"""The frozen graph definition's digest is a golden value, not a live recompute.

A dispatch and the checkpoint it writes trust :meth:`FrozenGraphDefinition.digest`
to stay byte-identical for byte-identical compiler inputs, across process restarts
and across machines. A change to the canonical encoding it is built from would
silently invalidate every durable receipt already written under the old digest,
so the value is pinned here rather than merely asserted "equal to itself".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...team.team_config import load_team_config
from ...testing import DEFAULT_TEAM_PRESET
from ..executable_graph import freeze_graph_definition

if TYPE_CHECKING:
    from pathlib import Path

#: The default team preset's frozen graph definition, pinned once against a
#: known-good run of :func:`freeze_graph_definition`. A deliberate change to
#: the preset or to the canonical encoding must update this value on purpose.
_GOLDEN_DIGEST = "c068d3cedd7169e910489e1585422832e8d304775586933775b2d0b8b5a890f9"


def test_the_default_preset_digest_is_pinned(tmp_path: Path) -> None:
    team = load_team_config(DEFAULT_TEAM_PRESET, workspace_root=tmp_path)
    definition = freeze_graph_definition(team, workspace_root=tmp_path)
    assert len(_GOLDEN_DIGEST) == 64
    assert definition.digest() == _GOLDEN_DIGEST


def test_the_digest_does_not_depend_on_the_absolute_workspace_path(
    tmp_path: Path,
) -> None:
    """Two distinct workspace roots freezing the same preset get the same digest."""
    other = tmp_path / "elsewhere"
    other.mkdir()
    first = freeze_graph_definition(
        load_team_config(DEFAULT_TEAM_PRESET, workspace_root=tmp_path),
        workspace_root=tmp_path,
    )
    second = freeze_graph_definition(
        load_team_config(DEFAULT_TEAM_PRESET, workspace_root=other),
        workspace_root=other,
    )
    assert first.digest() == second.digest() == _GOLDEN_DIGEST
