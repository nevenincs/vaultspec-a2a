"""Which fixtures cost a test its purity claim, asked of pytest not restated.

``unit`` is declared as "no I/O, no database, no HTTP". A test can acquire all
three without importing or calling anything: it names a fixture, and the fixture
is defined in a ``conftest.py`` one or more directories above it. Nothing in the
file records the dependency, so a scan of what a test file CALLS - the method
that found twenty-eight false purity claims - cannot see these at all. Following
fixtures across a configuration boundary needs a different mechanism rather than
a wider version of that one.

The mechanism is to ask pytest. By the time items are collected, each carries
the fixture closure pytest itself resolved, with conftest inheritance, autouse,
overrides and fixtures-requesting-fixtures already applied. Reimplementing any
part of that resolution would reintroduce exactly the drift the claim exists to
prevent: this module names the impure fixtures and lets pytest decide which
tests reach them.

A name here is a statement that the fixture performs real I/O when it runs, so
every test whose closure contains it is impure however pure its own body is.
Depending on such a fixture indirectly counts, because the closure is transitive.

A test can also testify against its own purity, and :func:`forfeits_purity` is
where that testimony is read. A ``service`` mark says the test drives real
services; a ``resource`` claim says it contends for something machine-global and
takes a lease to do so. Neither needs inferring - the test declared it - and
neither can be seen by a per-file list, because both are per-ITEM declarations
that live inside files also holding pure tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from .resources import MARKER_NAME as RESOURCE_MARKER

if TYPE_CHECKING:
    import pytest

__all__ = [
    "IMPURE_FIXTURES",
    "SERVICE_MARKER",
    "forfeits_purity",
    "uses_impure_fixture",
]

#: The mark by which a test states that it drives real services. Declared here
#: rather than beside a layer vocabulary because this is the only place its
#: MEANING is acted on: a test wearing it has already answered the purity
#: question about itself.
SERVICE_MARKER: Final = "service"

IMPURE_FIXTURES: Final = frozenset(
    {
        # Spawns a real Python child and hands over its actual stdio streams.
        "acp_session_context",
        # Reads a discovery record from disk and probes a live engine over HTTP.
        "live_engine",
    }
)


def uses_impure_fixture(item: pytest.Item) -> bool:
    """Return whether *item*'s resolved fixture closure reaches real I/O.

    Reads the closure pytest computed rather than the test's own signature, so
    a fixture pulled in transitively - or inherited from a ``conftest.py`` the
    test never mentions - counts the same as one the test names itself.
    """
    return not IMPURE_FIXTURES.isdisjoint(getattr(item, "fixturenames", ()))


def forfeits_purity(item: pytest.Item) -> bool:
    """Return whether *item* may not be granted the orthogonal purity claim.

    Three independent disqualifications, asked of the item rather than of the
    file it happens to sit in. That distinction is the whole point: a file-level
    exclusion cannot withhold a claim from ONE live test sharing a module with
    pure ones, and a package that tried carried live turns into its hermetic
    selection while its own list looked complete.

    The two declared disqualifications are the test's OWN testimony, so honouring
    them is reading a statement rather than making an inference. ``service`` says
    it drives real services; a ``resource`` claim says it contends for a
    machine-global resource and will take a lease to do so - a test with nothing
    shared to touch would have nothing to claim. Marker presence is read directly
    rather than through the claim parser, so deciding purity can never fail on a
    malformed declaration that the resource plugin is the right place to report.
    """
    return (
        uses_impure_fixture(item)
        or item.get_closest_marker(SERVICE_MARKER) is not None
        or item.get_closest_marker(RESOURCE_MARKER) is not None
    )
