"""The armed authoring preset declares the shape its attach seam keys on.

This module was written against ``assert_armed_authoring_attachable``, a
COMPILE-TIME gate in ``worker.graph_lifecycle``. That symbol never existed in any
committed version of the tree -- the file was committed against uncommitted work
that never landed -- so every test here failed at IMPORT, and because pytest
aborts a whole run on a collection error, no ``pytest src/vaultspec_a2a`` run
could complete at all. Every suite-wide green reported against this tree was in
fact a scoped subset that stepped around this module.

The behaviour those tests wanted does exist; it is ATTACH-TIME rather than
compile-time. ``_acp_authoring.attach_authoring_tools`` refuses a model with no
mount surface instead of returning it unchanged, which is the same refusal one
seam later -- before any turn runs, though not before the subprocess spawns.

What remains here is the armed-shape assertion. The attach seam itself is
proven on the real lane models rather than on stand-ins: the ACP lane's
``with_mcp_servers`` on a real ``AcpChatModel``, with the no-surface refusal and
the unarmed no-op, in ``providers/tests/test_acp_authoring.py``; the Codex lane's
``with_authoring_mcp_server`` on a real ``CodexChatModel`` through the same seam
in ``providers/tests/test_codex_config_home.py``.

Real config loading: the shipped ``vaultspec-solo-coder`` preset, no mocks.
"""

from __future__ import annotations

from ...team.team_config import load_team_config


def test_solo_coder_is_armed_via_authoring_bridge() -> None:
    """The armed shape is authoring_bridge=true with NO declared harness servers.

    A predicate keyed on ``mcp_servers`` alone would read this preset as unarmed
    and skip every attachment check, which is the class of gap this file exists
    to hold shut.
    """
    harness = load_team_config("vaultspec-solo-coder").effective_harness()
    assert harness is not None
    assert harness.authoring_bridge is True
    assert not harness.mcp_servers
