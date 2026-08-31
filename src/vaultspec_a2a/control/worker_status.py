"""The worker watchdog's connection-status vocabulary.

Sited in its own module rather than beside the watchdog that writes it because
the watchdog module is the largest in this package and the health projection
reads this vocabulary without needing anything else from it; a reader that only
has to answer "what can this field say" should not import a supervisor to find
out. :mod:`vaultspec_a2a.control.drain` is the same shape.

Deliberately NOT merged with the gateway contract's ``WorkerLifecycleState``,
which reads cold / starting / ready / unavailable. That one is the readiness
LADDER a client is served: it treats a worker that has never been asked for as
a resting state rather than a fault. This one is the watchdog's raw observation
of a process it supervises, and it has no notion of "not yet wanted". The
health projection maps this onto that, and collapsing the two would erase the
distinction that mapping exists to draw.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["WorkerConnectionStatus"]


class WorkerConnectionStatus(StrEnum):
    """What the watchdog last observed about the worker process it supervises.

    ``PENDING`` is the pre-observation value the state container is created
    with: a watchdog exists but has not yet completed a probe, which is not the
    same claim as ``DOWN``. ``UP`` and ``DOWN`` are settled observations,
    ``RESTARTING`` is the window in which the watchdog is deliberately replacing
    the process, and ``UNKNOWN`` is what a reader gets when no worker state
    container exists at all - a gateway configured without a supervised worker.
    """

    PENDING = "pending"
    UP = "up"
    DOWN = "down"
    RESTARTING = "restarting"
    UNKNOWN = "unknown"
