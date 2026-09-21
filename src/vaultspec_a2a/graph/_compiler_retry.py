"""Worker and supervisor retry policy."""

from __future__ import annotations

from langgraph.errors import GraphRecursionError
from langgraph.types import RetryPolicy

from ..providers.conditions import ProviderCondition, condition_is_retryable
from ..thread.errors import ProviderSessionError, WorkerExecutionError

__all__ = ["_NODE_RETRY_POLICY", "_worker_retry_on"]

# Transient exceptions that warrant a retry at the LangGraph node level.
_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    ConnectionResetError,
    ConnectionAbortedError,
    ConnectionRefusedError,
)

# Exceptions that must never trigger a retry.
_NO_RETRY_EXCEPTIONS: tuple[type[BaseException], ...] = (
    GraphRecursionError,
    ProviderSessionError,
)


def _resolved_condition(exc: BaseException) -> ProviderCondition | None:
    """Return the provider condition *exc* carries, or ``None`` when it carries none.

    Read off the attribute rather than matched against the provider exception
    classes on purpose. One of those classes is private to its own adapter module
    and importing either would pull a provider implementation into the compiler,
    which is the import cycle the providers package's lazy boundary exists to
    break. The attribute is the contract the lanes established at their raise
    sites; checking the VALUE's type is what keeps that loose read honest, since
    an unrelated ``condition`` attribute of some other type resolves to nothing
    rather than to a member.
    """
    condition = getattr(exc, "condition", None)
    if isinstance(condition, ProviderCondition):
        return condition
    return None


def _lane_retry_hint(exc: BaseException) -> bool | None:
    """Return the retry verdict the lane itself stated, or ``None`` for silence.

    One served lane answers this question outright: its error notification
    declares a required boolean beside the turn error, saying whether it would
    have made another attempt. Because this adapter abandons the turn on that
    notification rather than waiting for the lane's own retry, honouring the flag
    reinstates the attempt the lane intended rather than adding one it did not.

    Silence and a stated refusal are deliberately distinct. Only the frame that
    carries the flag can answer, so a failure raised anywhere else leaves this
    ``None`` and the inference below decides; reading an absent flag as a refusal
    would let one lane's shape veto every other lane's condition.
    """
    hint = getattr(exc, "will_retry", None)
    if isinstance(hint, bool):
        return hint
    return None


def _retry_verdict(exc: BaseException) -> bool:
    """Decide whether one unwrapped failure is worth another attempt.

    Three axes, in descending order of how directly each answers the question.

    A hint the lane STATED wins outright, in both directions: it is the provider's
    own verdict on its own failure, arriving for free on a frame already parsed,
    and preferring a conclusion we derived over one the vendor sent would be
    strictly worse information. A stated refusal is as authoritative as a stated
    intent - the lane saying it is done trying is exactly the signal that stops a
    pointless round of backoff.

    Absent a hint, the resolved condition answers, and it outranks the type axis
    because a condition is a statement about what the provider refused while a
    type match is an inference from the exception's base class. That ordering also
    leaves the stdlib types untouched: they carry neither hint nor condition, so
    they still reach the type axis exactly as before.

    Which conditions are retryable is NOT decided here. It is one judgement,
    declared beside the vocabulary and read both by this policy and by the flag a
    client is served, so what the graph does and what the client is told cannot
    drift apart.
    """
    hint = _lane_retry_hint(exc)
    if hint is not None:
        return hint

    condition = _resolved_condition(exc)
    if condition is not None:
        return condition_is_retryable(condition)
    return isinstance(exc, _TRANSIENT_EXCEPTIONS)


def _retry_wrapped_worker_error(exc: WorkerExecutionError) -> bool:
    # Retrying after relayed output would duplicate text already sent to the client.
    if exc.relayed_output:
        return False
    cause = exc.__cause__
    if cause is None:
        return False
    # A tool may have changed external state even when no text was relayed.
    if getattr(cause, "effects_may_have_occurred", False) is True:
        return False
    if isinstance(cause, _NO_RETRY_EXCEPTIONS):
        return False
    return _retry_verdict(cause)


def _worker_retry_on(exc: Exception) -> bool:
    """Predicate passed to ``RetryPolicy`` for every worker node.

    Inspects the direct exception and, for ``WorkerExecutionError`` wrappers,
    the ``__cause__`` to determine whether a retry is appropriate. The wrapper
    case is the production shape for a provider fault: the worker node chains the
    provider exception onto its wrapper, so the cause is where the condition is.

    Returns:
        ``True``  -- transient failure, retry is safe.
        ``False`` -- permanent or indeterminate failure, do not retry.
    """
    # Never retry deterministic or quota errors.
    if isinstance(exc, _NO_RETRY_EXCEPTIONS):
        return False

    # WorkerExecutionError wraps the original cause -- inspect it.
    if isinstance(exc, WorkerExecutionError):
        return _retry_wrapped_worker_error(exc)

    return _retry_verdict(exc)


#: RetryPolicy applied to every worker and supervisor node (T05). Every timing
#: field is explicit so a LangGraph dependency update cannot silently widen the
#: number of attempts or the elapsed retry budget. The served ACP wire exposes
#: no retry delay and Codex exposes only ``willRetry``, so there is no provider
#: duration to merge into this fixed local schedule.
_NODE_RETRY_POLICY = RetryPolicy(
    initial_interval=0.5,
    backoff_factor=2.0,
    max_interval=1.0,
    max_attempts=3,
    jitter=False,
    retry_on=_worker_retry_on,
)
