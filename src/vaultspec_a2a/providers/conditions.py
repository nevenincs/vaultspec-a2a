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
    "codex_mapped_error_infos",
    "condition_from_acp_error",
    "condition_from_codex_error_info",
    "condition_from_codex_turn_error",
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
    """The request cannot succeed as sent; changing it is the remedy.

    The operative property is that retrying the SAME request cannot help - the
    request itself has to change. That is what a consumer should act on, and it
    is the only claim every mapped discriminator supports.

    Deliberately wider than "the provider rejected it as malformed". Three
    distinct shapes land here, and only the first is a malformed-input refusal:
    a bad shape or unknown model; a policy refusal the provider understood and
    declined on its own terms; and an output or context ceiling reached, which
    may be a CLIENT-configured cap rather than a provider limit and may mean a
    response was truncated rather than refused. Copy written for this member
    must not tell a user their request was invalid, because for the ceiling case
    nothing was wrong with it.
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


# --- Codex lane -------------------------------------------------------------
#
# The app-server's turn error carries a ``codexErrorInfo`` discriminator beside
# its message. It takes two shapes: a bare string for the categorical failures,
# and a single-key object for the ones that additionally forward an upstream
# HTTP status. Both are handled, and the status is preferred where present
# because it is the more specific statement about what the provider did.
#
# This lane separates an exhausted usage allowance from other refusals in its
# own right, so the finer usage member is honest here in a way it is not on the
# ACP lane. It also names a session budget and a connection failure, which are
# the only routes to the budget and unreachable members anywhere in this tree.

_CODEX_ERROR_INFO_CONDITIONS: Mapping[str, ProviderCondition] = {
    "unauthorized": ProviderCondition.UNAUTHENTICATED,
    # Named on the wire as an exhausted usage allowance, so the finer member is
    # a report of what arrived rather than an inference.
    "usageLimitExceeded": ProviderCondition.USAGE_EXHAUSTED,
    # A ceiling the caller configured for the session, which is exactly what
    # the budget member means and what separates it from the credits member.
    "sessionBudgetExceeded": ProviderCondition.BUDGET_EXHAUSTED,
    "serverOverloaded": ProviderCondition.PROVIDER_OVERLOADED,
    "badRequest": ProviderCondition.INVALID_REQUEST,
    # The prompt exceeded the model's context. Retrying it unchanged repeats
    # the failure; the request has to get smaller.
    "contextWindowExceeded": ProviderCondition.INVALID_REQUEST,
    # A policy refusal: understood, and declined on the provider's own terms.
    # No member describes a policy decision, and the invalid member is the one
    # whose remedy - change the request - actually applies.
    "cyberPolicy": ProviderCondition.INVALID_REQUEST,
    # A server-side fault that does not claim overload, mapped to the floor for
    # the same reason as the ACP lane's generic server fault.
    "internalServerError": ProviderCondition.UNKNOWN,
    # Local failures of the app-server's own machinery rather than statements
    # about the provider, so neither has an honest member here.
    "threadRollbackFailed": ProviderCondition.UNKNOWN,
    "sandboxError": ProviderCondition.UNKNOWN,
    "other": ProviderCondition.UNKNOWN,
}

_CODEX_OBJECT_INFO_CONDITIONS: Mapping[str, ProviderCondition] = {
    # Each of these names a failure to reach or hold the provider connection,
    # which is the one discriminator in this tree that supports the unreachable
    # member. When one of them forwards an HTTP status the status wins, since a
    # status means the provider answered.
    "httpConnectionFailed": ProviderCondition.NETWORK_UNREACHABLE,
    "responseStreamConnectionFailed": ProviderCondition.NETWORK_UNREACHABLE,
    "responseStreamDisconnected": ProviderCondition.NETWORK_UNREACHABLE,
    # Retries were exhausted. That says how the attempt ended, not why the
    # provider refused, so without a forwarded status there is nothing to
    # report beyond the floor.
    "responseTooManyFailedAttempts": ProviderCondition.UNKNOWN,
    # The turn could not accept this request in its current state - a rejection
    # of what was asked, for reasons the caller can address.
    "activeTurnNotSteerable": ProviderCondition.INVALID_REQUEST,
}

_CODEX_HTTP_STATUS_CONDITIONS: Mapping[int, ProviderCondition] = {
    400: ProviderCondition.INVALID_REQUEST,
    401: ProviderCondition.UNAUTHENTICATED,
    # Payment required: the account cannot fund the request.
    402: ProviderCondition.CREDITS_EXHAUSTED,
    403: ProviderCondition.UNAUTHENTICATED,
    404: ProviderCondition.INVALID_REQUEST,
    413: ProviderCondition.INVALID_REQUEST,
    422: ProviderCondition.INVALID_REQUEST,
    # The one status that states a rate refusal outright. This is how the
    # throttled member is reached on a lane whose categorical vocabulary has no
    # rate member of its own.
    429: ProviderCondition.THROTTLED,
}
# Server-side statuses are deliberately absent above. A 5xx says the provider
# failed, not that it is over capacity, and this lane names overload explicitly
# when it means it; inferring overload from a status would put a wait-and-retry
# remedy in front of a client on evidence the wire never gave.


def codex_mapped_error_infos() -> frozenset[str]:
    """Return the Codex error-info variants this module resolves explicitly.

    Covers both shapes the discriminator takes - the bare categorical strings
    and the keys of the object variants - so coverage can assert that every
    variant the INSTALLED app-server schema declares was decided here rather
    than left to fall through to the floor.
    """
    return frozenset(_CODEX_ERROR_INFO_CONDITIONS) | frozenset(
        _CODEX_OBJECT_INFO_CONDITIONS
    )


def _codex_http_status_condition(payload: object) -> ProviderCondition | None:
    """Resolve an object variant's forwarded HTTP status, when it carries one."""
    if not isinstance(payload, dict):
        return None
    status = payload.get("httpStatusCode")
    if not isinstance(status, int) or isinstance(status, bool):
        return None
    return _CODEX_HTTP_STATUS_CONDITIONS.get(status)


def condition_from_codex_error_info(info: object) -> ProviderCondition:
    """Resolve one Codex ``codexErrorInfo`` value into a provider condition.

    Total, on the same terms as the ACP resolver: a shape this function does not
    recognise, a variant this vocabulary predates, and an absent discriminator
    all yield the unknown member rather than raising.
    """
    if isinstance(info, str):
        return _CODEX_ERROR_INFO_CONDITIONS.get(info, ProviderCondition.UNKNOWN)
    if not isinstance(info, dict):
        return ProviderCondition.UNKNOWN

    # The variant is a single-key object, but the declared table is iterated
    # rather than the payload so a malformed frame carrying several keys still
    # resolves the same way every time.
    named: dict[str, object] = {
        key: value for key, value in info.items() if isinstance(key, str)
    }
    for variant, condition in _CODEX_OBJECT_INFO_CONDITIONS.items():
        if variant not in named:
            continue
        from_status = _codex_http_status_condition(named[variant])
        return from_status if from_status is not None else condition
    return ProviderCondition.UNKNOWN


def condition_from_codex_turn_error(error: object) -> ProviderCondition:
    """Resolve one Codex turn error into a provider condition.

    The turn error is the shape carried both by the app-server's error
    notification and by a failed turn's own ``error`` field. Its message is
    never consulted: the discriminator beside it is the whole point, and a
    message that classified would break the moment the vendor reworded it.
    """
    if not isinstance(error, dict):
        return ProviderCondition.UNKNOWN
    return condition_from_codex_error_info(error.get("codexErrorInfo"))
