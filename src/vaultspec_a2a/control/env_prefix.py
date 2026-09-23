"""The prefix every a2a-owned environment variable carries.

A leaf of its own so that a process which only needs to spell a name - the test
runner, which starts before anything else and is timed - does not pay for the
settings machinery to learn it.
"""

__all__ = ["ENV_PREFIX"]

ENV_PREFIX = "VAULTSPEC_A2A_"
