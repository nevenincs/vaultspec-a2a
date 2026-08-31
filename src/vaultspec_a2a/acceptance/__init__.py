"""Reusable real-process certification harness for the assembled A2A product.

This package is the deterministic real-process fixture the terminal
certification wave asserts against, and the fixture the assembling dashboard
repository drives against the same stack it certifies. It boots the production
gateway armed with the desktop profile over a genuinely migrated application
home, lets the gateway own and spawn its own worker, and returns an
authenticated handle to the versioned public surface.

Nothing here is a test double. The stack is the real gateway process, a real
gateway-owned worker process, the provider the worker proxies to, and real
SQLite control and checkpoint stores, reached over real loopback HTTP behind the
dashboard-created attach-control credential. The harness never authenticates
through the test-only bypass: it presents a real ``Authorization: Bearer`` attach
credential exactly as the dashboard does.

The harness is import-safe production infrastructure - it never imports pytest -
so a non-Python consumer can drive it too. It is source-and-certification-only:
it depends on the bundled deterministic preset that exists only in source and
Compose certification environments, so it is excluded from the runtime wheel.
"""

from __future__ import annotations

from ._harness import (
    DEFAULT_REQUIRED_ROLE,
    DEFAULT_TEAM_PRESET,
    CertifiedGateway,
    certified_gateway,
)

__all__ = [
    "DEFAULT_REQUIRED_ROLE",
    "DEFAULT_TEAM_PRESET",
    "CertifiedGateway",
    "certified_gateway",
]
