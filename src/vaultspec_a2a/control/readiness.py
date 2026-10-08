"""Gateway readiness vocabulary and the authenticated desktop readiness projection.

Control computes every one of these facts and its admission broker consumes them,
so the vocabulary is sited here and the api layer imports it to serve it: the
dependency runs api to control, never the other way.
:mod:`vaultspec_a2a.control.health` is the single authority that assembles
:class:`DesktopReadiness`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "API_VERSION",
    "DesktopReadiness",
    "GatewayReadiness",
    "LivenessState",
    "ProviderEligibility",
    "RunAdmission",
    "WorkerLifecycleState",
]

# The one wire version stamp: the readiness projection carries it here and every
# gateway response model in the api layer reads it from this definition.
API_VERSION = "v1"


class LivenessState(StrEnum):
    """Minimal process-liveness fact: the gateway answered, or it did not.

    This is the only fact an unauthenticated caller ever observes. It proves
    neither ownership nor readiness and discloses no product state.
    """

    ALIVE = "alive"
    NOT_ALIVE = "not_alive"


class GatewayReadiness(StrEnum):
    """Whether a live gateway with a valid database is ready to be attached.

    Independent of worker state: a live gateway with a valid database and a cold,
    startable worker is ``ready``. A gateway-owned dependency failure - an invalid
    or unreachable database - is ``not_ready``.
    """

    READY = "ready"
    NOT_READY = "not_ready"


class WorkerLifecycleState(StrEnum):
    """The gateway-owned worker's rung on the cold-to-execution ladder.

    ``cold`` is the pre-demand resting state: no worker exists yet and one is
    startable on first execution demand. It is informational, never degradation.
    ``starting`` is the single-flight startup window, ``ready`` is an up and
    reachable worker, and ``unavailable`` is a worker that started but is down or
    restarting after demand.
    """

    COLD = "cold"
    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"


class ProviderEligibility(StrEnum):
    """Whether at least one subprocess provider may be served work on this host.

    Decided by lane admission, which requires a recorded completed-turn proof
    for the lane, a resolved launcher whose reported version that proof admits,
    and the lane's own readiness - its configuration present and its launch
    command resolvable. All three, conjunctively.

    Credential readiness is NECESSARY and never SUFFICIENT: a lane whose
    credential resolves and whose launcher is installed is still ``ineligible``
    until a live test has completed a real turn on it. An eligibility that
    stopped at the credential served lanes with handshake coverage only, which
    is the whole reason the proof term exists. No provider is constructed to
    decide this, and the launcher's version report is cached per launch identity.
    """

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class RunAdmission(StrEnum):
    """Whether the gateway would admit a run right now - the execution-ready fact.

    ``ready`` means execution-ready: a reachable worker and a provider this host
    may be served, so this staged gate and the admission gate launch applies
    agree, rather than admitting a run and reserving capacity for it that the
    latter then refuses.
    ``deferred`` means gateway-ready but not yet execution-ready - the worker is
    cold or starting and will start on demand. It remains informational on the
    readiness surface, while staged ``prepare`` admission refuses it fail-closed.
    ``blocked`` means a hard dependency or the profile's required native
    execution isolation is unavailable. Attachment can remain gateway-ready.
    """

    READY = "ready"
    DEFERRED = "deferred"
    BLOCKED = "blocked"


class DesktopReadiness(BaseModel):
    """The authenticated desktop readiness projection.

    Carries process and product identity alongside the five separate bounded
    readiness facts. The facts are never collapsed into a single boolean: a cold,
    startable worker leaves ``gateway_readiness`` ``ready`` while ``run_admission``
    stays ``deferred`` or ``blocked``, so attachment and execution readiness
    remain distinct. Served only to an attach-authenticated caller.
    """

    api_version: Literal["v1"] = API_VERSION
    # Process identity.
    gateway_pid: int
    # Product identity: the running product generation and its profile.
    generation: str
    profile: str
    # The five separate bounded facts.
    liveness: LivenessState = LivenessState.ALIVE
    gateway_readiness: GatewayReadiness
    worker_state: WorkerLifecycleState
    provider_eligibility: ProviderEligibility
    eligible_providers: list[str] = Field(default_factory=list, max_length=16)
    run_admission: RunAdmission
    # Bounded, path-free reasons explaining a not-ready, cold, or deferred fact.
    reasons: list[str] = Field(default_factory=list, max_length=16)
