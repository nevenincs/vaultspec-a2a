"""Unauthenticated gateway liveness wire type."""

from __future__ import annotations

from pydantic import BaseModel

from ...control.readiness import LivenessState

__all__ = ["LivenessResponse"]


class LivenessResponse(BaseModel):
    """The unauthenticated liveness body.

    Deliberately minimal: it carries only the liveness fact and discloses no
    process identity, product identity, or product state. An unauthenticated
    caller of the desktop gateway observes this and nothing more.
    """

    liveness: LivenessState = LivenessState.ALIVE
