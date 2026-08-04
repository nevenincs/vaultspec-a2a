"""Lifecycle test configuration — layer markers by file.

Pure-logic lifecycle tests are ``core`` + ``unit``; the discovery tests exercise
real filesystem, process, and HTTP I/O, so they are ``middleware`` (infra
services) instead — keeping the marker selections a clean partition.
"""

import pytest

_PACKAGE_DIR = str(__import__("pathlib").Path(__file__).resolve().parent)

# Files whose tests drive real infrastructure (fs/process/HTTP) rather than pure
# domain logic; marked middleware instead of core+unit.
_INFRA_FILES = frozenset(
    {
        "test_discovery.py",
        "test_registry.py",
        "test_procs_config.py",
        "test_manager.py",
        "test_registration.py",
        "test_live_concurrency.py",
        "test_engine_serve.py",
    }
)


# Core-layer lifecycle tests that really do launch a child process. They stay
# ``core`` - they are domain tests, not infrastructure ones - but they are not
# pure, so the orthogonal ``unit`` claim is withheld. A wrong marker is worse
# than none: a selection excluding impure tests silently includes anything
# missing here, and the run is then believed hermetic when it is not.
_IMPURE_CORE_FILES = frozenset({"test_pairing.py", "test_singleton.py"})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests from THIS directory by layer according to what they exercise."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if item.path.name in _INFRA_FILES:
            item.add_marker(pytest.mark.middleware)
        else:
            item.add_marker(pytest.mark.core)
            if item.path.name not in _IMPURE_CORE_FILES:
                item.add_marker(pytest.mark.unit)
