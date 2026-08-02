"""The resource-aware execution plugin.

Wires the declaration vocabulary into pytest so that:

- **Placement follows declarations.** Every item's ``xdist_group`` is computed
  from its declared exclusive resources; items whose exclusive sets overlap
  land in one group (union-find over keys), so a ``--dist=loadgroup`` run
  serializes them on one worker while disjoint groups may run concurrently.
  Undeclared items inside the live tiers are funneled into one serial
  catch-all group - the safe assumption for a test that touches real services
  without saying which.
- **Distribution is never a gamble.** ``-n`` under any xdist mode other than
  ``loadgroup`` aborts with a usage error; blind ``load``/``each`` placement
  of resource-bound tests is unreachable.
- **Exclusion does not depend on placement.** An autouse fixture takes a
  machine-global lease per declared claim before the test body runs, so two
  claimants of one exclusive resource cannot overlap even across unrelated
  test sessions on the same host.
- **Timeout backstops derive from declarations.** An item claiming a resource
  with a declared backstop is raised to it, replacing the one arbitrary global
  clock for live tests; progress deadlines (``testing.progress``) remain the
  real arbiter of a hung wait.
- **Acquisition goes through the real machinery.** ``gateway_endpoint`` and
  ``worker_endpoint`` resolve through the dev-process registry, and
  ``leased_port`` allocates from the scratch band with the registry's own
  race-free reservation - never a hardcoded default.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import pytest

from .resources import (
    MARKER_NAME,
    ResourceClaim,
    ResourceDeclarationError,
    declared_claims,
    exclusive_keys,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..conftest import ExternalPrerequisiteRule
    from ..lifecycle import PortReservation
    from .endpoints import ResolvedService
    from .leases import Lease

# Directories whose tests exercise real services; an undeclared item under one
# of these is scheduled as maximally contended rather than gambled on.
_LIVE_TIER_DIRS = frozenset({"service_tests", "acceptance", "desktop_tests"})
_SERIAL_CATCHALL_GROUP = "undeclared-live-serial"
_GROUP_PREFIX = "res:"


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """Register the marker vocabulary and refuse blind distribution modes.

    Configure-time runs after xdist's tryfirst ``pytest_cmdline_main`` has
    normalized ``-n`` into its ``dist`` default, so a plain ``-n auto``
    (implicit ``--dist=load``) is caught as reliably as an explicit blind
    mode. Only declaration-driven ``loadgroup`` placement is admitted.
    """
    config.addinivalue_line(
        "markers",
        f"{MARKER_NAME}(key, shared=False): declare that this test uses the "
        "named contended resource; drives scheduling groups, machine-global "
        "leases, and timeout backstops (see vaultspec_a2a.testing).",
    )
    numprocesses = config.getoption("numprocesses", default=None)
    dist = config.getoption("dist", default="no")
    if numprocesses and dist != "loadgroup":
        raise pytest.UsageError(
            f"-n/--numprocesses requires --dist=loadgroup in this repository "
            f"(got --dist={dist}): concurrency must be a consequence of "
            "declared resource disjointness, never blind distribution. "
            "Run: pytest -n <N> --dist=loadgroup"
        )


class _UnionFind:
    """Union-find over resource keys, for merging overlapping exclusive sets."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, key: str) -> str:
        parent = self._parent.setdefault(key, key)
        if parent == key:
            return key
        root = self.find(parent)
        self._parent[key] = root
        return root

    def union(self, left: str, right: str) -> None:
        self._parent[self.find(right)] = self.find(left)

    def members(self) -> dict[str, list[str]]:
        components: dict[str, list[str]] = {}
        for key in list(self._parent):
            components.setdefault(self.find(key), []).append(key)
        return components


def _is_live_tier(item: pytest.Item) -> bool:
    return any(part in _LIVE_TIER_DIRS for part in item.path.parts)


def _claims_or_usage_error(item: pytest.Item) -> tuple[ResourceClaim, ...]:
    try:
        return declared_claims(item)
    except ResourceDeclarationError as exc:
        raise pytest.UsageError(str(exc)) from exc


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Derive placement groups and timeout backstops from the declarations.

    Deterministic on the collected item set, so every xdist worker computes
    identical groups. Items with no claims outside the live tiers get no
    group and remain freely distributable - the in-process bulk of the suite.
    """
    del config
    unions = _UnionFind()
    item_claims: list[tuple[pytest.Item, tuple[ResourceClaim, ...]]] = []
    for item in items:
        claims = _claims_or_usage_error(item)
        item_claims.append((item, claims))
        keys = exclusive_keys(claims)
        for key in keys[1:]:
            unions.union(keys[0], key)
    components = unions.members()
    group_names = {
        root: _GROUP_PREFIX + "+".join(sorted(members))
        for root, members in components.items()
    }
    for item, claims in item_claims:
        keys = exclusive_keys(claims)
        if keys:
            item.add_marker(pytest.mark.xdist_group(group_names[unions.find(keys[0])]))
        elif not claims and _is_live_tier(item):
            item.add_marker(pytest.mark.xdist_group(_SERIAL_CATCHALL_GROUP))
        backstop = max((claim.spec.backstop_s for claim in claims), default=0)
        if backstop > 0 and item.get_closest_marker("timeout") is None:
            item.add_marker(pytest.mark.timeout(backstop))


def _gate_probeable_prerequisites(
    request: pytest.FixtureRequest, claims: tuple[ResourceClaim, ...]
) -> None:
    """Route claimed, probeable prerequisites through the repository's one rule.

    Where the root conftest's ``external_prerequisite`` fixture exists, an
    absent prerequisite skips (or fails, when guaranteed) with the canonical
    runbook reason BEFORE a lease is taken, so contended leases are never held
    across an honest skip. Probe-less prerequisites (the calling suite probes
    those itself) and sessions outside the repository conftest pass through.
    """
    probeable = [
        claim.spec.prerequisite_id for claim in claims if claim.spec.prerequisite_id
    ]
    if not probeable:
        return
    try:
        rule = request.getfixturevalue("external_prerequisite")
    except pytest.FixtureLookupError:
        return
    from ..conftest import EXTERNAL_PREREQUISITES

    probes = {p.id: p.probe for p in EXTERNAL_PREREQUISITES}
    for prerequisite_id in probeable:
        if probes.get(prerequisite_id) is not None:
            rule(prerequisite_id)


@pytest.fixture(autouse=True)
def resource_leases(request: pytest.FixtureRequest) -> Iterator[dict[str, Lease]]:
    """Hold one machine-global lease per declared claim for the test's duration.

    Autouse, so a declared exclusive resource is leased even by a test that
    never asks for the handles - exclusion must not be opt-in. Acquisition
    order is the claims' sorted-by-key order, identical for every claimant,
    so two tests claiming overlapping sets cannot deadlock. Tests wanting the
    handles (to inspect holder metadata) request the fixture by name.
    """
    claims = declared_claims(request.node)
    if not claims:
        yield {}
        return
    _gate_probeable_prerequisites(request, claims)
    from .leases import hold_lease

    held: dict[str, Lease] = {}
    with contextlib.ExitStack() as stack:
        for claim in claims:
            held[claim.spec.key] = stack.enter_context(
                hold_lease(
                    claim.spec.key,
                    shared=claim.shared,
                    owner=request.node.nodeid,
                )
            )
        yield held


def _require_declaration(request: pytest.FixtureRequest, key: str) -> None:
    claimed = {claim.spec.key for claim in declared_claims(request.node)}
    if key not in claimed:
        pytest.fail(
            f"{request.node.nodeid} requests a {key!r}-backed fixture without "
            f"declaring it; add @pytest.mark.resource({key!r}) so the scheduler "
            "and the lease layer can see the dependency."
        )


@pytest.fixture
def gateway_endpoint(request: pytest.FixtureRequest) -> ResolvedService:
    """The live a2a gateway, resolved through the dev-process registry.

    Requires the ``loopback-stack`` declaration; an absent gateway reports
    through the repository's one external-prerequisite rule, so
    ``--require-prerequisite=loopback-stack`` turns the skip into a failure.
    """
    _require_declaration(request, "loopback-stack")
    from .endpoints import resolve_gateway_url

    resolved = resolve_gateway_url()
    if resolved is None:
        rule: ExternalPrerequisiteRule = request.getfixturevalue(
            "external_prerequisite"
        )
        rule.absent(
            "loopback-stack",
            "no environment override and no LIVE, health-answering gateway-dev "
            "record in the dev-process registry",
        )
    return resolved


@pytest.fixture
def worker_endpoint(request: pytest.FixtureRequest) -> ResolvedService:
    """The live a2a worker, resolved through the dev-process registry."""
    _require_declaration(request, "loopback-stack")
    from .endpoints import resolve_worker_url

    resolved = resolve_worker_url()
    if resolved is None:
        rule: ExternalPrerequisiteRule = request.getfixturevalue(
            "external_prerequisite"
        )
        rule.absent(
            "loopback-stack",
            "no environment override and no LIVE, health-answering worker-dev "
            "record in the dev-process registry",
        )
    return resolved


@pytest.fixture
def leased_port() -> Iterator[int]:
    """An exclusively-reserved scratch-band port, via the registry's allocator.

    The same race-free reserve the lifecycle verbs use: an ``O_EXCL`` marker
    in the machine-global procs home, so two concurrent claimants - workers,
    sessions, or agents - can never receive the same port. Released at
    teardown. Suited to binds held for the test's duration; the reservation's
    TTL backstop assumes bounded holds, so a test holding one for longer than
    a few minutes should boot through ``serve_up`` instead.
    """
    from ..lifecycle import load_procs_config, release_reservation, reserve_port

    config = load_procs_config()
    reservation: PortReservation = reserve_port(
        "scratch", config.role("scratch"), config=config
    )
    try:
        yield reservation.port
    finally:
        release_reservation(reservation)
