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
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    import pytest

__all__ = ["IMPURE_FIXTURES", "uses_impure_fixture"]

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
