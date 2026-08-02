"""The machine-readable test-resource vocabulary.

A test that uses a contended real resource - a live service stack, a provider
CLI lane's usage window, a shared workspace - declares it with the ``resource``
marker::

    @pytest.mark.resource("loopback-stack")
    @pytest.mark.resource("run-artifacts", shared=True)

The declaration is the single source three consumers read:

- the scheduler derives ``xdist_group`` placement from it, so tests sharing an
  exclusive resource serialize while disjoint ones may run concurrently;
- the acquisition fixtures take a machine-global lease per declared claim, so
  exclusion holds even when placement is wrong;
- the per-item timeout backstop is derived from the claimed specs, replacing
  the one arbitrary global clock for resource-bound tests.

Keys must name a cataloged :class:`ResourceSpec`, with one deliberate escape
hatch: keys prefixed ``scratch-`` are admitted ad hoc as exclusive,
prerequisite-free resources, so framework self-tests and one-off experiments
can exercise the real contention machinery without polluting the catalog.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

__all__ = [
    "MARKER_NAME",
    "RESOURCES",
    "SCRATCH_PREFIX",
    "ResourceClaim",
    "ResourceDeclarationError",
    "ResourceSpec",
    "declared_claims",
    "exclusive_keys",
    "resolve_spec",
]

MARKER_NAME = "resource"
SCRATCH_PREFIX = "scratch-"


class ResourceDeclarationError(Exception):
    """A test declared a resource the vocabulary does not admit."""


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    """One contended resource the suite knows how to schedule and lease.

    ``prerequisite_id`` links the resource to the root conftest's
    ``ExternalPrerequisite`` of the same id, so ``--require-prerequisite``
    semantics extend over resource-gated tests unchanged. ``backstop_s`` is the
    pytest-timeout ceiling a claiming test is raised to - a LAST-RESORT guard
    against wedged test code, never the arbiter of a slow live turn (progress
    deadlines are); zero leaves the suite default in force.
    """

    key: str
    description: str
    prerequisite_id: str = ""
    backstop_s: int = 0


@dataclass(frozen=True, slots=True)
class ResourceClaim:
    """One declared use of a resource by one test item."""

    spec: ResourceSpec
    shared: bool


# The canonical catalog. Every entry names a resource the suite genuinely
# contends on; the live-service entries carry generous backstops because a
# legitimate live model turn is slow and must not be killed for being slow.
_CATALOG: tuple[ResourceSpec, ...] = (
    ResourceSpec(
        key="loopback-stack",
        description=(
            "the reachable loopback engine plus a2a gateway and worker; runs "
            "drive engine state serially"
        ),
        prerequisite_id="loopback-stack",
        backstop_s=1800,
    ),
    ResourceSpec(
        key="compose-stack",
        description=(
            "the docker-compose deterministic service stack; one stack per "
            "host, session-scoped"
        ),
        prerequisite_id="docker",
        backstop_s=1800,
    ),
    ResourceSpec(
        key="claude-cli-lane",
        description="the Claude Code ACP CLI's live usage window",
        prerequisite_id="claude-cli",
        backstop_s=1800,
    ),
    ResourceSpec(
        key="codex-cli-lane",
        description="the Codex CLI's live usage window",
        prerequisite_id="codex-cli",
        backstop_s=1800,
    ),
    ResourceSpec(
        key="kimi-cli-lane",
        description="the Kimi CLI's live usage window",
        prerequisite_id="kimi-cli",
        backstop_s=1800,
    ),
    ResourceSpec(
        key="zai-lane",
        description="the Z.ai credentialed provider lane's live usage window",
        prerequisite_id="zai-credential",
        backstop_s=1800,
    ),
)

RESOURCES: dict[str, ResourceSpec] = {spec.key: spec for spec in _CATALOG}


def resolve_spec(key: str) -> ResourceSpec:
    """Return the spec for *key*, admitting ad-hoc ``scratch-`` keys.

    Raises :class:`ResourceDeclarationError` for an uncataloged key, so a typo
    in a declaration fails collection loudly instead of silently detaching a
    test from the resource it actually uses.
    """
    spec = RESOURCES.get(key)
    if spec is not None:
        return spec
    if key.startswith(SCRATCH_PREFIX):
        return ResourceSpec(
            key=key, description="ad-hoc scratch resource (framework validation)"
        )
    raise ResourceDeclarationError(
        f"unknown test resource {key!r}; cataloged keys: {sorted(RESOURCES)} "
        f"(ad-hoc keys must start with {SCRATCH_PREFIX!r})"
    )


def declared_claims(item: pytest.Item) -> tuple[ResourceClaim, ...]:
    """The resource claims *item* declares, in stable (sorted-by-key) order.

    A key claimed both shared and exclusive collapses to exclusive - the
    stronger claim governs both scheduling and leasing.
    """
    strongest: dict[str, bool] = {}
    for marker in item.iter_markers(name=MARKER_NAME):
        if len(marker.args) != 1 or not isinstance(marker.args[0], str):
            raise ResourceDeclarationError(
                f"{item.nodeid}: @pytest.mark.resource takes exactly one string "
                f"key, got args={marker.args!r}"
            )
        unknown = set(marker.kwargs) - {"shared"}
        if unknown:
            raise ResourceDeclarationError(
                f"{item.nodeid}: @pytest.mark.resource admits only the 'shared' "
                f"keyword, got {sorted(unknown)!r}"
            )
        key = marker.args[0]
        shared = bool(marker.kwargs.get("shared", False))
        strongest[key] = strongest.get(key, True) and shared
    return tuple(
        ResourceClaim(spec=resolve_spec(key), shared=shared)
        for key, shared in sorted(strongest.items())
    )


def exclusive_keys(claims: tuple[ResourceClaim, ...]) -> tuple[str, ...]:
    """The sorted exclusive keys of *claims* - the scheduling signature."""
    return tuple(claim.spec.key for claim in claims if not claim.shared)
