"""The closed vocabulary of provider failure conditions.

A failed run has to tell a client something it can act on, and the actions are
genuinely different: wait, re-authenticate, top up, raise a spend limit, shorten
the request, or report a bug. This module names those outcomes once, so every
served lane maps its own wire discriminator into the same set and no consumer
has to pattern-match vendor prose to work out which one happened.

The vocabulary is deliberately SMALLER than the set of distinctions the
providers collectively make, because it admits only distinctions at least one
served lane can actually carry. Where a lane's wire cannot separate two members,
that lane maps to the coarser one rather than guessing; the finer member is
emitted only by a lane whose wire names it. Two members are asymmetric in
exactly this way and are documented on the members themselves.

Mapping into this vocabulary is TOTAL by contract: every lane mapper accepts any
input and returns a member, with :attr:`ProviderCondition.UNKNOWN` as the floor.
A mapper may not raise and may not return nothing, because it runs on a path
that is already failing and a second failure there costs the client the only
diagnosis it was going to get.

This is a wire contract consumed by a second repository, so it is additive-only:
a member may be added, but no member's spelling or meaning may change.
"""

from collections.abc import Mapping
from enum import StrEnum

__all__ = [
    "ProviderCondition",
    "acp_mapped_error_kinds",
    "condition_from_acp_error",
]


class ProviderCondition(StrEnum):
    """Why a provider failed, in terms a client can act on.

    The value is the wire form: lowercase, underscore-separated, and stable.
    """

    NETWORK_UNREACHABLE = "network_unreachable"
    """The provider could not be reached at all.

    A transport-level failure before any model was engaged. Distinct from
    :attr:`PROVIDER_OVERLOADED`, which is the provider answering to refuse.
    """

    PROVIDER_OVERLOADED = "provider_overloaded"
    """The provider answered that it is temporarily over capacity.

    Retryable and not the caller's fault. Reserved for a wire discriminator
    that names overload specifically; a generic server-side fault is NOT this
    member, because reporting one as overload asserts a cause and a remedy
    (wait) that the wire never stated.
    """

    UNAUTHENTICATED = "unauthenticated"
    """The credential was missing, rejected, or not permitted for this account.

    The remedy is a credential action - log in again, supply a key, or switch
    account - as opposed to waiting or paying.
    """

    THROTTLED = "throttled"
    """The request was refused for rate, and retrying later is the remedy.

    On lanes whose wire cannot separate a short-term rate refusal from an
    exhausted usage window, this is the member both collapse to. That is a hard
    information limit on those lanes rather than an implementation gap: their
    adapter assigns one kind to both cases and consumes the distinguishing
    signal internally, so emitting :attr:`USAGE_EXHAUSTED` there would assert a
    distinction the wire does not carry.
    """

    USAGE_EXHAUSTED = "usage_exhausted"
    """A usage allowance for the plan or period is spent.

    Waiting helps only when the window rolls over, so the remedy is usually a
    plan change rather than a retry. Emitted ONLY by a lane whose wire names
    usage-limit exhaustion in its own right; a lane that reports rate refusals
    and window exhaustion identically emits :attr:`THROTTLED` instead.
    """

    CREDITS_EXHAUSTED = "credits_exhausted"
    """The account's billable balance cannot fund the request.

    The remedy is a billing action. Distinct from :attr:`BUDGET_EXHAUSTED`,
    which is a self-imposed ceiling the operator can lift without paying.
    """

    BUDGET_EXHAUSTED = "budget_exhausted"
    """A configured spend or session budget stopped the request.

    The ceiling is the caller's own, so the remedy is to raise or reset it.
    Emitted only by a lane whose wire names a budget control specifically.
    """

    INVALID_REQUEST = "invalid_request"
    """The provider rejected the request as malformed or unsatisfiable.

    Covers a request the provider understood and refused on its own terms - a
    bad shape, an unknown model, or a length past a hard model limit. Retrying
    the same request cannot help; the request itself has to change.
    """

    UNKNOWN = "unknown"
    """The failure carried no discriminator this lane can resolve.

    The floor of every mapping, and a normal outcome rather than a defect: a
    lane may fail in ways its wire does not classify, and saying so plainly is
    more useful than promising a condition that was never observed. It is what
    an unrecognised or absent discriminator resolves to, which is what keeps a
    mapper total when a provider adds a discriminator this vocabulary predates.
    """


# --- ACP lane (Claude and Z.ai over the same adapter) ------------------------
#
# The adapter attaches a categorical ``errorKind`` to ``data`` on its failure
# frames, drawn from the agent SDK's closed union, precisely so a client can
# dispatch on it instead of pattern-matching the human-readable message. That
# kind is the primary discriminator here; the JSON-RPC code is the fallback for
# the failures raised before or outside a model turn, which carry no kind.
#
# Z.ai rides this same adapter against a redirected base URL, and a live probe
# on that gateway returned a faithful kind on a status-gated rejection, so one
# mapping serves both lanes. Kinds the CLI derives by matching Anthropic's own
# English prose are not attested there and should be expected to arrive as a
# coarser kind on that lane - which this mapping handles by construction,
# because it is total and its floor is truthful.

_ACP_KIND_CONDITIONS: Mapping[str, ProviderCondition] = {
    # Credential rejected outright. Observed live on the Z.ai gateway.
    "authentication_failed": ProviderCondition.UNAUTHENTICATED,
    # The credential is valid but its organization forbids this login method.
    # The remedy is a credential or account action, not waiting or paying, so
    # it belongs with the other credential failures rather than apart.
    "oauth_org_not_allowed": ProviderCondition.UNAUTHENTICATED,
    # The provider's billing refusal. It does NOT separate a depleted balance
    # from a reached spend ceiling, so the coarser of the two paid-remedy
    # members is used; the budget member stays reserved for a lane that names a
    # caller-configured ceiling in its own right, which this lane never does.
    "billing_error": ProviderCondition.CREDITS_EXHAUSTED,
    # The hard information limit on this lane. The CLI assigns this one kind to
    # a short-term rate refusal AND to an exhausted usage window, branching
    # between them only on a response header it consumes internally. Mapping it
    # to the finer usage member would assert a distinction that never crossed
    # the wire, so it collapses to the coarser member by design.
    "rate_limit": ProviderCondition.THROTTLED,
    "overloaded": ProviderCondition.PROVIDER_OVERLOADED,
    "invalid_request": ProviderCondition.INVALID_REQUEST,
    # The request named a model this account or endpoint does not serve; the
    # request has to change, which is what the invalid member means.
    "model_not_found": ProviderCondition.INVALID_REQUEST,
    # The turn ran into the model's output ceiling. Retrying unchanged repeats
    # it, so this is a request-shape problem rather than a transient one.
    "max_output_tokens": ProviderCondition.INVALID_REQUEST,
    # A server-side fault that is NOT stated to be overload. Reporting it as
    # overload would tell a client to wait on evidence the wire never gave, so
    # it resolves to the floor deliberately rather than by omission.
    "server_error": ProviderCondition.UNKNOWN,
    "unknown": ProviderCondition.UNKNOWN,
    # The adapter's own kind, raised when a turn ends with no result at all. It
    # is outside the SDK union but reaches the same field.
    "no_result": ProviderCondition.UNKNOWN,
}

_ACP_CODE_CONDITIONS: Mapping[int, ProviderCondition] = {
    # The adapter's authentication-required refusal, raised during session
    # setup before any turn and therefore never carrying an error kind.
    -32000: ProviderCondition.UNAUTHENTICATED,
    # JSON-RPC's own request-level rejections. A malformed frame, an unknown
    # method or bad parameters are all faults in what was asked, and none of
    # them is fixed by retrying the same call.
    -32700: ProviderCondition.INVALID_REQUEST,
    -32600: ProviderCondition.INVALID_REQUEST,
    -32601: ProviderCondition.INVALID_REQUEST,
    -32602: ProviderCondition.INVALID_REQUEST,
    # The frame that CARRIES an error kind. Reaching this entry means the kind
    # was absent or unrecognised, and the internal-error code alone says
    # nothing further about why.
    -32603: ProviderCondition.UNKNOWN,
    # Cancellation and a missing resource are real outcomes with no member in
    # this vocabulary, which is about why a PROVIDER refused work. Mapped
    # explicitly so they are recorded as considered rather than overlooked.
    -32800: ProviderCondition.UNKNOWN,
    -32002: ProviderCondition.UNKNOWN,
}


def acp_mapped_error_kinds() -> frozenset[str]:
    """Return the ACP error kinds this module resolves explicitly.

    Exposed so coverage can assert that every kind the INSTALLED adapter can
    emit has a considered entry here. Totality alone is too weak a property to
    test for - the floor makes every input return something - so the meaningful
    question is whether a kind reaches its member by decision or by falling
    through, and this set is what distinguishes the two.
    """
    return frozenset(_ACP_KIND_CONDITIONS)


def condition_from_acp_error(error: object) -> ProviderCondition:
    """Resolve one ACP JSON-RPC error object into a provider condition.

    Total: any input yields a member. A malformed frame, an absent discriminator
    and a discriminator this vocabulary predates all resolve to the unknown
    member rather than raising, because this runs on a path that is already
    failing and a second failure there costs the client its only diagnosis.

    The error kind is preferred over the JSON-RPC code because it is the
    finer-grained signal and the one the adapter documents for dispatch; the
    code answers only for the failures raised outside a turn, which carry none.
    """
    if not isinstance(error, dict):
        return ProviderCondition.UNKNOWN

    data = error.get("data")
    if isinstance(data, dict):
        kind = data.get("errorKind")
        if isinstance(kind, str):
            mapped = _ACP_KIND_CONDITIONS.get(kind)
            if mapped is not None:
                return mapped

    code = error.get("code")
    if isinstance(code, int) and not isinstance(code, bool):
        return _ACP_CODE_CONDITIONS.get(code, ProviderCondition.UNKNOWN)
    return ProviderCondition.UNKNOWN
