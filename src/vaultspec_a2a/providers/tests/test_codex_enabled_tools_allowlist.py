"""``enabled_tools`` is the registry's declaration, not the caller's suggestion.

The Codex ``config.toml`` writes each server's ``tools`` into ``enabled_tools``
beside ``default_tools_approval_mode = "auto"``, under a run whose
``approval_policy`` is ``"never"``. That pairing is what makes an unverified list
dangerous rather than untidy: a tool named there is invoked without a prompt and
without anything having compared it to what was reviewed. The rag server exposes
``reindex_vault`` and ``reindex_codebase``, which the registry deliberately omits
to hold the read-only composition boundary, so the divergence that matters is a
SUPERSET - and its failure mode is silence. Nothing raises; a write verb simply
becomes auto-approved.

Production could not reach that state by construction even before the comparison
existed, because both readings now resolve from one renderer and one tools
reader. That is exactly the condition this campaign's governing record says the
next author bypasses: a correctness that lives in the current call graph rather
than in the seam. ``mcp_servers`` specs are ordinary mappings and the renderer is
a public function.

The refusal tests below would each pass against a renderer that refused
EVERYTHING, so the admitted cases are asserted as deliberately as the refusals:
a conforming registry spec renders, and the authoring bridge - which names
mutating tools on purpose and is deliberately not registry-known - still renders
untouched. A skip that turned into a refusal would disarm the entire Codex
authoring lane, which is the more expensive failure of the two.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Any

import pytest

from ...thread.errors import ConfigError
from ...utils.enums import CodexWebSearchMode
from .._acp_authoring import AUTHORING_MCP_SERVER_NAME
from .._acp_mcp import codex_mcp_server_specs, declared_harness_tools
from .._codex_config_home import (
    _SPEC_LAUNCH_KEYS,
    _SPEC_SURFACE_KEYS,
    _SPEC_VARIANT_KEYS,
    registry_tools_divergence,
    render_codex_config_toml,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .._json_contract import JsonObject

_RAG = "vaultspec-rag"

#: The verbs the rag server also exposes and the registry withholds. Named from
#: the registry's own commentary rather than copied from a failing run.
_WRITE_VERBS = ("reindex_vault", "reindex_codebase")


def _bridge_spec() -> JsonObject:
    """The authoring bridge's flat spec, in the shape the renderer consumes.

    Its ``tools`` name a mutating verb on purpose - the bridge's trust root is
    that the engine authored it, not that the registry reviewed it.
    """
    return {
        "name": AUTHORING_MCP_SERVER_NAME,
        "command": "python",
        "args": ["-m", "vaultspec_a2a.protocols.mcp.authoring_stdio"],
        "tools": ["read_context", "propose_changeset"],
    }


def _with_tools(spec: JsonObject, tools: Sequence[str]) -> JsonObject:
    """Return *spec* carrying *tools* as its declared surface.

    A copy-then-replace rather than a fresh literal, so the spec keeps every
    other field the producer emitted - a hand-rebuilt spec would quietly drop a
    field and test a shape production never renders.
    """
    divergent: JsonObject = dict(spec)
    divergent["tools"] = list(tools)
    return divergent


def _render(specs: list[JsonObject]) -> dict[str, Any]:
    return tomllib.loads(
        render_codex_config_toml(specs, web_search=CodexWebSearchMode.DISABLED)
    )


def test_the_declared_surface_withholds_the_write_verbs() -> None:
    """The premise every other test rests on, asserted rather than assumed.

    If the registry ever declared a write verb, the superset test below would be
    comparing against a surface that already admits one and would prove nothing.
    """
    declared = declared_harness_tools(_RAG)

    assert declared, "the registry declares no tools for the rag server"
    for verb in _WRITE_VERBS:
        assert verb not in declared


def test_a_conforming_registry_spec_is_written_unchanged() -> None:
    """The admitted case. Without it every refusal here could be vacuous."""
    parsed = _render(codex_mcp_server_specs([_RAG]))

    server = parsed["mcp_servers"][_RAG]
    assert tuple(server["enabled_tools"]) == declared_harness_tools(_RAG)
    assert server["default_tools_approval_mode"] == "auto"


@pytest.mark.parametrize(
    ("label", "tools"),
    [
        ("superset", [*declared_harness_tools(_RAG), *_WRITE_VERBS]),
        ("write verb alone", list(_WRITE_VERBS)),
        ("subset", list(declared_harness_tools(_RAG))[:1]),
        ("reordered", list(reversed(declared_harness_tools(_RAG)))),
        ("empty", []),
    ],
)
def test_a_spec_whose_tools_diverge_is_refused(label: str, tools: list[str]) -> None:
    """Any divergence from the declaration is refused, not merely the dangerous one.

    The superset is the security case - it is the one that reaches
    ``enabled_tools`` as an auto-approved write verb. The others are included
    because a comparison that admitted them would be checking membership rather
    than equality, and "exactly the registry's read tools" is what the renderer's
    own docstring claims.
    """
    [spec] = codex_mcp_server_specs([_RAG])
    divergent = [_with_tools(spec, tools)]

    with pytest.raises(ConfigError, match="registry entry declares"):
        render_codex_config_toml(divergent, web_search=CodexWebSearchMode.DISABLED)


def test_the_refusal_names_the_auto_approval_that_makes_it_matter() -> None:
    """The message has to carry WHY, since the reader is whoever assembled a spec."""
    [spec] = codex_mcp_server_specs([_RAG])
    divergent = [_with_tools(spec, [*declared_harness_tools(_RAG), *_WRITE_VERBS])]

    with pytest.raises(ConfigError) as excinfo:
        render_codex_config_toml(divergent, web_search=CodexWebSearchMode.DISABLED)

    message = str(excinfo.value)
    assert "enabled_tools" in message
    assert "default_tools_approval_mode" in message
    assert "reindex_vault" in message


def test_a_server_the_registry_does_not_own_is_skipped_not_refused() -> None:
    """The authoring bridge's skip, at the comparison itself.

    The bridge carries no static registry declaration, so there is nothing to
    compare it against - and it names mutating tools deliberately, because its
    trust root is that the engine authored it rather than that the registry
    reviewed it.
    """
    bridge = _bridge_spec()

    assert registry_tools_divergence(bridge, name=AUTHORING_MCP_SERVER_NAME) is None

    parsed = _render([bridge])
    written = parsed["mcp_servers"][AUTHORING_MCP_SERVER_NAME]
    assert written["enabled_tools"] == ["read_context", "propose_changeset"]


def test_the_bridge_rides_beside_a_registry_server_in_one_render() -> None:
    """Both halves in one config, so the skip cannot be a blanket exemption.

    A comparison that skipped every spec would satisfy the bridge test above on
    its own. Rendering both together requires the registry server to be compared
    while the bridge is not.
    """
    [rag] = codex_mcp_server_specs([_RAG])
    bridge = _bridge_spec()

    parsed = _render([rag, bridge])
    servers = parsed["mcp_servers"]
    assert set(servers) == {_RAG, AUTHORING_MCP_SERVER_NAME}

    # ...and the registry half is still compared while they travel together.
    both = [_with_tools(rag, _WRITE_VERBS), bridge]
    with pytest.raises(ConfigError, match="registry entry declares"):
        render_codex_config_toml(both, web_search=CodexWebSearchMode.DISABLED)


def test_the_compared_fields_partition_what_the_producer_emits() -> None:
    """Every field a Codex spec carries is classified, so none goes uncompared.

    Asserted against the keys ``codex_mcp_server_specs`` actually produces rather
    than against a union of the three constants, which would agree with itself no
    matter what the producer did. A field added to the Codex serialization lands
    here as a failure until someone decides which part it belongs to - which is
    the review ``tools`` never got.
    """
    surface, launch, variant = (
        set(_SPEC_SURFACE_KEYS),
        set(_SPEC_LAUNCH_KEYS),
        set(_SPEC_VARIANT_KEYS),
    )

    assert surface.isdisjoint(launch)
    assert surface.isdisjoint(variant)
    assert launch.isdisjoint(variant)

    [pinned] = codex_mcp_server_specs([_RAG], project_root="Y:/proj")
    assert set(pinned) == surface | launch | variant
