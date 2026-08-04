"""A2A's opinionated default entry for one execution lane.

A new run carries no implicit provider or model, and the catalog contract keeps
it that way: presets carry topology and personas but no provider policy, and the
client sends only values A2A served. That leaves a real product gap - a first-run
user faces a list with nothing chosen - which this closes WITHOUT reintroducing
what the catalog contract removed.

The opinion is a RULE over what a lane already advertises, never a list of model
names. Nothing here names an external model, encodes a tier, or maps a size onto
a provider; a lane that starts advertising a new model gets a recommendation for
it with no repository release. That is the whole distinction from the static
model map this replaced: a map goes stale the moment a provider ships, a rule
does not.

The recommendation is a2a's, not the lane's, so it is served beside the catalog
rather than folded into it - the domain catalog keeps saying exactly what the
provider said. It is a DEFAULT, not a constraint: every other served entry stays
equally selectable, and a client that pre-selects this one still lets the user
change it.

Effort is a different axis and is deliberately not decided here. Low/medium/high
belongs to the provider that advertises it and already rides on the lane's native
controls with the provider's own default option; expressing a model choice as a
tier is precisely the centrally maintained mapping this design refuses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .provider_catalog import ProviderCatalog

__all__ = ["recommended_entry_id"]

# Capability tokens are provider-issued strings, so this is a preference over
# VOCABULARY a lane may or may not use - not a claim that any lane uses it. A
# lane advertising none of these simply falls through to its own ordering, which
# is why the absence of a match is not a failure.
_PREFERRED_CAPABILITIES: tuple[str, ...] = ("reasoning", "thinking", "agentic")


def recommended_entry_id(catalog: ProviderCatalog) -> str | None:
    """Return the entry A2A would pre-select on *catalog*, or ``None``.

    ``None`` is the honest answer for a lane advertising nothing selectable, and
    is distinct from recommending an arbitrary entry: a client must be able to
    tell "we have an opinion" from "there is nothing to have an opinion about".

    The rule, in order:

    1. an entry whose capability vocabulary marks it as the lane's reasoning-grade
       choice - the closest a lane comes to declaring its own best entry;
    2. otherwise the lane's FIRST entry, because provider enumerations are
       ordered by the provider and its own ordering is a better default than any
       ranking invented here.

    Both steps look like the two things the operator-facing resolver refuses by
    name - it never ranks entries and never falls back to the first one - and the
    difference is worth stating, because a reader who finds only one of the two
    modules will reasonably read the other as contradicting it.

    That resolver RESOLVES an entry the operator already named: choosing on their
    behalf there would silently decide what produces their artifacts and what a
    provider charges for them, so it must refuse. This RECOMMENDS a starting
    point nobody has chosen yet, which is the one job that requires choosing.
    Its answer is a default a client pre-selects and a user overrides, never a
    substitute for an absent choice at run start - run start still refuses a
    request that names no entry. Choosing for someone who has not chosen, and
    choosing for someone who has, are opposite acts wearing the same shape.
    """
    if not catalog.models:
        return None
    for capability in _PREFERRED_CAPABILITIES:
        for model in catalog.models:
            if capability in model.capabilities:
                return model.entry_id
    return catalog.models[0].entry_id
