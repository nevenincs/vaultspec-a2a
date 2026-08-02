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

from enum import StrEnum

__all__ = ["ProviderCondition"]


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
