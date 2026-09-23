"""The harness's environment names, importable without the settings stack.

The test runner is the first process of every run and its startup is timed, so
it spells these names from the shared prefix instead of importing the settings
class that reads them. ``testing/tests/test_session_root.py`` holds every name
here equal to what :class:`~.session_root.TestSessionSettings` actually reads.
"""

from ..control.env_prefix import ENV_PREFIX

__all__ = [
    "COMPLETION_ENDPOINT_ENV",
    "COMPLETION_OWNER_PID_ENV",
    "CPU_BUDGET_ENV",
    "TEST_ENV_PREFIX",
]

#: The prefix of every harness variable.
TEST_ENV_PREFIX = f"{ENV_PREFIX}TEST_"

COMPLETION_ENDPOINT_ENV = f"{TEST_ENV_PREFIX}COMPLETION_ENDPOINT"
COMPLETION_OWNER_PID_ENV = f"{TEST_ENV_PREFIX}COMPLETION_OWNER_PID"
CPU_BUDGET_ENV = f"{TEST_ENV_PREFIX}CPU_BUDGET"
