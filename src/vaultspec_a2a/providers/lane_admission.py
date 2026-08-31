"""Lane admission: which provider lanes carry proof of which completed capability.

This module holds every per-lane capability declaration in one place, because a
lane's admission for one capability and its activation for another are the same
kind of claim - a human recording that a live test watched real work finish on
that lane - and splitting them across modules is how two registries start
disagreeing. Two capabilities are declared here today: completed-turn proof, which
decides whether a lane may be SERVED at all, and completed-web-retrieval proof,
which decides whether a served lane's web grounding ACTIVATES.

Completed-turn proof
--------------------

A served model profile may name a provider lane only after a live test has
COMPLETED A REAL TURN on that lane - a real prompt, through the real transport,
producing real model output. Construction-only coverage, config-parse coverage,
and live pre-auth handshake coverage do not qualify: a handshake proves spawn,
not work.

This module is the machine-readable form of that admission rule. It exists
because the rule previously lived only as prose: the eligibility service asked
"is a credential present and does the command resolve", never "has this lane ever
completed a turn", and so a handshake-proven lane was served to the composer as a
selectable profile the backend had never done work with.

**Credential readiness is necessary but NOT sufficient.** Readiness
(:func:`..model_profiles.probe_provider_readiness`) and admission (this module)
are separate verdicts, deliberately kept apart so a refusal names which one
failed. A lane with a perfectly valid credential and a perfectly resolvable
command is still refused here until a human records its completed-turn proof.

**The declaration is hand-edited, and deny is the default.** :data:`PROVEN_TURN_LANES`
is a literal a person must consciously edit, each entry naming the live test that
earns it. It is deliberately NOT derived by scanning for test files, introspecting
markers, or matching module names: a derived set would silently re-admit a lane the
moment somebody added an unrelated test, which is the same unenforced-rule failure
one layer down. Anything absent from the declaration is unproven, so a newly added
:class:`~..graph.enums.Provider` member is refused from birth until its proof is
recorded here.

Adding a lane is therefore a deliberate act with a fixed cost: run the live test,
watch it complete a real turn, then add the entry citing that test by node id.

Completed-web-retrieval proof
----------------------------

:data:`PROVEN_WEB_LANES` is the same rule for the web-grounding capability, and it
is deliberately a SIBLING of the turn declaration rather than a field on
:class:`LaneProof`. Three things force that shape. The two proofs are earned and
withdrawn independently - upstream tool drift can cost a lane its web activation
while it keeps serving turns perfectly - and folding them into one record would
make withdrawing one an edit to the other's citation. The turn side admits lanes
through TWO declarations, the mapping and :data:`IN_PROCESS_LANES`, and the
in-process lanes must never be web-proven: they spawn no CLI, so there is nothing
there to retrieve with, and a field hanging off :class:`LaneProof` could not have
expressed that at all, because those lanes hold no proof record. And the consumers
differ: turn admission is a REFUSAL consulted by the eligibility service, while web
proof is an ACTIVATION consulted by tool and persona composition.

What keeps the sibling from becoming a registry that can disagree with the turn one
is not a shared container but an enforced implication, asserted at import by
:func:`_require_web_proof_implies_turn_proof`: every web-proven lane must appear in
:data:`PROVEN_TURN_LANES`. A retrieval is work completed on a lane, so a lane that
cannot be shown to complete a turn cannot be shown to complete a retrieval, and the
incoherent state - a lane activated for web that is refused for service - is
unrepresentable rather than merely unlikely.

The set is EMPTY at first landing, by design: the tree carries the wiring before it
carries the PROOF, so every seam is asserted dark and no persona claims a reach it
cannot demonstrate.

Read "dark" precisely, because the distinction is a decided one and this module is
where a reader will come looking for it. Every lane is CAPABLE of reaching the web -
that is a property of the lane's own first-party tools and is never conditional on
lane, role, preset, or proof. What an empty set withholds is ACTIVATION and the
right to CLAIM: which tools compose into a run, and what a persona or a served
preset may assert about reach. A lane absent from here is unproven, never incapable,
and this mapping is not a capability veto. A gate that read it as one was built and
withdrawn.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..graph.enums import Provider
from ..thread.errors import ConfigError
from .in_process_catalog import IN_PROCESS_EXECUTION_MODES
from .provider_catalog import ProviderCatalogKey

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "IN_PROCESS_CATALOG_LANES",
    "IN_PROCESS_LANES",
    "PROVEN_CATALOG_TURN_LANES",
    "PROVEN_TURN_LANES",
    "PROVEN_WEB_LANES",
    "LaneProof",
    "WebLaneProof",
    "catalog_lane_admission_reason",
    "is_catalog_lane_admissible",
    "is_lane_admissible",
    "is_web_lane_proven",
    "lane_admission_reason",
    "unproven_lanes_in",
    "web_tool_names_for",
]


@dataclass(frozen=True, slots=True)
class LaneProof:
    """The live test that earned one provider lane its served admission.

    ``test`` is the pytest node id of the proof, so a reviewer can re-run the
    exact thing that admitted the lane. ``proves`` states what that run completed
    in one line - it is the claim being made, and it must describe finished work,
    never a spawn, a handshake, or a successful construction.
    """

    test: str
    proves: str


@dataclass(frozen=True, slots=True)
class WebLaneProof:
    """The live test that earned one provider lane its web-grounding activation.

    The same evidentiary standard as :class:`LaneProof`, one capability along:
    ``test`` is the pytest node id of the live proof and ``proves`` states in one
    line what that run COMPLETED - a real retrieval that reached checkpointed state
    as a typed web locator and the proposed document body as a disclosed source. A
    surfaced tool name, an allowlist entry, or a parsed config is not a retrieval.

    ``tool_names`` are the exact native built-in names the proven retrieval was
    performed with, and they are what the lane's activation composes into the
    autonomous allowlist. They ride the proof rather than a lane-blind constant so
    a lane activates exactly what its own proof exercised, and so a lane whose web
    reach is CONFIGURED rather than permitted can be proven with no names at all -
    an empty tuple is the honest declaration for a lane that enables search through
    its per-run config home and exposes no allowlist name. This field selects among
    tools rather than declaring one: every composed name must still have stated its
    network-egress axis where native tool names are declared, and composing one
    that has not is refused there.
    """

    test: str
    proves: str
    tool_names: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# THE DECLARATION - edit by hand, never derive.
#
# Add an entry ONLY after watching the cited test complete a real turn on that
# lane. Removing a lane is always safe; adding one is a claim about work that
# actually finished. Do not add a lane because a test file exists, because a
# credential resolves, because a handshake succeeded, or because construction
# passed - none of those are turns.
#
# Deliberately absent, with the coverage they actually have:
#   - kimi    handshake only (test_kimi_handshake_live.py proves the installed
#             `kimi acp` speaks our handshake - that is spawn, not work)
#   - gemini  auth/construction coverage only; no completed turn
#   - openai  no live turn coverage
#   - zhipu   no live coverage of any kind
# ---------------------------------------------------------------------------
PROVEN_TURN_LANES: Mapping[Provider, LaneProof] = MappingProxyType(
    {
        Provider.CLAUDE: LaneProof(
            test=(
                "src/vaultspec_a2a/providers/tests/test_claude_live_turn.py"
                "::test_claude_live_turn_completes_and_returns_content"
            ),
            proves="a real Claude turn completes through the production chain "
            "and returns model content",
        ),
        Provider.CODEX: LaneProof(
            test=(
                "src/vaultspec_a2a/service_tests/test_pw7_acceptance.py"
                "::test_pw7_research_adr_materializes_two_documents[codex]"
            ),
            proves="a real research-to-ADR acceptance run completes with the "
            "authoring roles on the codex lane",
        ),
        Provider.ZAI: LaneProof(
            test=(
                "src/vaultspec_a2a/providers/tests/test_zai_fidelity.py"
                "::test_zai_streaming_shape_is_faithful"
            ),
            proves="a real Z.ai turn against the real endpoint streams assistant "
            "content through the production ACP path",
        ),
    }
)

# Catalog serving is execution-mode specific.  The older profile admission API is
# provider-shaped, so it cannot safely answer this question: a future transport
# for an already-proven provider must not inherit another transport's evidence.
# Keep this declaration literal and deny-by-default for the same reason as the
# provider-level proof map above.  A later migration can move every legacy
# consumer onto this exact identity once profiles carry an execution mode.
PROVEN_CATALOG_TURN_LANES: Mapping[ProviderCatalogKey, LaneProof] = MappingProxyType(
    {
        ProviderCatalogKey("codex", "codex-app-server"): PROVEN_TURN_LANES[
            Provider.CODEX
        ],
    }
)

# The in-process lanes: no external transport exists to complete a turn against,
# so the completed-turn standard cannot be applied to them and does not gate them.
# MOCK proxies the in-repo tape server and DETERMINISTIC runs entirely in-process
# (the acceptance provider). Both are admitted by this explicit declaration, never
# by falling through the check - an unlisted lane must always land on deny.
IN_PROCESS_LANES: frozenset[Provider] = frozenset(
    {Provider.MOCK, Provider.DETERMINISTIC}
)

# The same in-process admission at CATALOG identity, and it is a SEPARATE
# declaration for the reason the catalog map above is separate from the
# provider-level one: catalog admission is execution-mode specific, so admitting
# a provider does not admit every mode it might one day be served under. An
# in-process provider offered under some other execution mode is not this
# declaration and still lands on deny.
#
# It is derived from :data:`IN_PROCESS_LANES` and the serving module's mode
# declaration rather than hand-listed, and that is deliberate in a module whose
# rule is otherwise "edit by hand, never derive". The hand-editing rule protects
# claims about work that finished on a lane; these lanes make no such claim, and
# their identity is exactly "the in-process lanes, under the modes they are
# served as". Restating the pair here would create a second place for a renamed
# execution mode to be forgotten, which is the failure mode this module exists to
# prevent, not an instance of the vigilance it asks for.
IN_PROCESS_CATALOG_LANES: frozenset[ProviderCatalogKey] = frozenset(
    ProviderCatalogKey(provider.value, IN_PROCESS_EXECUTION_MODES[provider])
    for provider in IN_PROCESS_LANES
)

# ---------------------------------------------------------------------------
# THE WEB DECLARATION - edit by hand, never derive. It landed EMPTY, because the
# wiring lands before the PROOF and every seam is asserted dark until a live run
# earns it. Absence still means no lane has yet demonstrated a retrieval, never
# that a lane cannot reach the web - capability is universal and this mapping
# governs activation and claims alone.
#
# Add an entry ONLY after watching the cited test complete a REAL RETRIEVAL on
# that lane end to end - the fetched material reaching checkpointed state as a
# typed web locator and the proposed document body as a disclosed source. Do not
# add a lane because its web tool surfaced, because its allowlist carried the
# name, because its config declared the feature, or because the model said it
# searched. None of those are retrievals, and each of them is the failure this
# gate exists to make impossible: a persona claiming a reach its tools do not
# have.
#
# Adding a lane here flips its web tools and its persona text together, in one
# change, for that lane only. Removing a lane is always safe.
# ---------------------------------------------------------------------------
PROVEN_WEB_LANES: Mapping[Provider, WebLaneProof] = MappingProxyType(
    {
        # No tool names: this lane's web reach is CONFIGURED, through the
        # ``web_search`` posture of its per-run config home, and it exposes no
        # allowlistable built-in to compose. The empty tuple is the honest
        # declaration for that shape, not an omission.
        Provider.CODEX: WebLaneProof(
            test=(
                "src/vaultspec_a2a/service_tests/test_codex_web_grounding_live.py"
                "::test_retrieval_returns_a_current_fact_the_model_cannot_recall"
            ),
            proves="a real codex turn under the served live posture retrieved a "
            "value only the live index could supply, and the same prompt under "
            "the disabled posture performed no search at all",
        ),
        # Only ``WebFetch`` is declared, because only ``WebFetch`` was exercised.
        # The proven run's agent reached the web by fetching named URLs; its
        # ``WebSearch`` sibling never fired, so composing it here would activate a
        # tool on the strength of another tool's evidence - the exact substitution
        # this declaration exists to refuse. ``WebSearch`` is earned by its own run.
        Provider.CLAUDE: WebLaneProof(
            test=(
                "src/vaultspec_a2a/service_tests/test_claude_web_grounding_live.py"
                "::test_claude_lane_completes_a_real_web_retrieval"
            ),
            proves="a real autonomous claude run fetched a live URL and carried the "
            "retrieved value into checkpointed state as a typed web locator and into "
            "the proposed research document's Sources section",
            tool_names=("WebFetch",),
        ),
    }
)


def _require_web_proof_implies_turn_proof(
    web: Mapping[Provider, WebLaneProof],
    turn: Mapping[Provider, LaneProof],
) -> None:
    """Fail loud unless every web-proven lane also carries completed-turn proof.

    The single rule that keeps the two declarations from disagreeing. A retrieval
    is work completed on a lane, so a lane with no completed turn cannot have
    completed a retrieval; and the in-process lanes, admitted for service by
    :data:`IN_PROCESS_LANES` rather than by proof, spawn no CLI and have nothing
    to retrieve with. Checked at import against the real declarations, so an
    incoherent pair - a lane activated for web while refused for service - cannot
    be committed and discovered later at a spawn.

    Raises:
        ConfigError: If any web-proven lane is absent from *turn*.
    """
    unbacked = [lane.value for lane in web if lane not in turn]
    if unbacked:
        raise ConfigError(
            "refusing a web-grounding activation for lane(s) with no completed-turn "
            f"proof: {', '.join(sorted(unbacked))}. A lane must be servable before "
            "its web capability can activate; record the completed-turn proof first, "
            "or drop the web entry"
        )


_require_web_proof_implies_turn_proof(PROVEN_WEB_LANES, PROVEN_TURN_LANES)


def _lane_of(provider: Provider | str | None) -> Provider | None:
    """Resolve a lane identity from a provider value, or ``None`` when unknown.

    Callers hold the lane as the bounded string an ACP model carries rather than
    as an enum member, and a run whose model never declared its lane is the normal
    unidentified case (hosted APIs, the in-repo mock). Both land on ``None`` here
    so every gate below denies by default instead of raising at a composition
    seam - an unidentifiable lane is exactly a lane with no recorded proof.
    """
    if isinstance(provider, Provider):
        return provider
    if not provider:
        return None
    try:
        return Provider(provider)
    except ValueError:
        return None


def is_lane_admissible(provider: Provider) -> bool:
    """Return whether *provider* may be named by a served model profile.

    True for a lane with recorded completed-turn proof and for the in-process
    lanes. False for everything else, including any provider this module has
    never heard of - deny is the default.
    """
    return provider in PROVEN_TURN_LANES or provider in IN_PROCESS_LANES


def is_catalog_lane_admissible(key: ProviderCatalogKey) -> bool:
    """Return whether this exact execution lane may be served as selectable.

    True for an external lane with recorded completed-turn proof and for the
    in-process lanes under the exact modes they are served as. False for
    everything else, including an in-process provider named under a foreign
    execution mode - deny is the default here as it is one layer up.
    """
    return key in PROVEN_CATALOG_TURN_LANES or key in IN_PROCESS_CATALOG_LANES


def catalog_lane_admission_reason(key: ProviderCatalogKey) -> str | None:
    """Return a safe refusal reason for an unproven exact catalog lane."""
    if is_catalog_lane_admissible(key):
        return None
    return (
        f"provider lane {key.provider_id}/{key.execution_mode} has no exact "
        "completed-turn proof; evidence from another execution mode is not inherited"
    )


def lane_admission_reason(provider: Provider) -> str | None:
    """Return why *provider* may not be served, or ``None`` when it is admissible.

    The reason names the provider and states the standard it failed, so a refusal
    served to the composer or raised at launch is self-explaining. Safe by
    construction: it carries no credential, path, or environment value.
    """
    if is_lane_admissible(provider):
        return None
    return (
        f"provider {provider.value} has no completed-turn proof; a served profile "
        "may name a lane only after a live test completes a real turn on it "
        "(a handshake, a resolved credential, or a constructed client is not a turn)"
    )


def unproven_lanes_in(providers: Iterable[Provider]) -> list[Provider]:
    """Return the inadmissible lanes among *providers*, order-preserving and deduped.

    Takes any iterable of provider values - a role's primary plus its declared
    fallbacks, a whole profile's lanes - and reports every one that fails
    admission, so a caller can name all of them at once rather than refusing on
    the first and hiding the rest.
    """
    seen: set[Provider] = set()
    unproven: list[Provider] = []
    for provider in providers:
        if provider in seen:
            continue
        seen.add(provider)
        if not is_lane_admissible(provider):
            unproven.append(provider)
    return unproven


def is_web_lane_proven(provider: Provider | str | None) -> bool:
    """Return whether *provider* may present itself as web-capable.

    The persona-composition half of the gate: True only for a lane carrying
    recorded completed-retrieval proof, so the no-online-access disclaimer stays
    the default for every other lane, including one this module has never heard of
    and a model that declared no lane at all.
    """
    lane = _lane_of(provider)
    return lane is not None and lane in PROVEN_WEB_LANES


def web_tool_names_for(provider: Provider | str | None) -> tuple[str, ...]:
    """Return the web built-in names *provider* has earned, empty when unproven.

    The tool-composition half of the gate, and the reason it returns names rather
    than a verdict: an unproven lane composes an empty tuple, which is
    indistinguishable at the composition seam from composing nothing, so the
    capability is dark by the same code path that later lights it. A proven lane
    with no names - web reach configured rather than permitted - is empty here too
    and correctly adds nothing to the allowlist.
    """
    lane = _lane_of(provider)
    if lane is None:
        return ()
    proof = PROVEN_WEB_LANES.get(lane)
    return proof.tool_names if proof is not None else ()
