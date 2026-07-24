"""Real-seam tests for the frozen-aware self-execution authority.

The rendered argv shapes are exercised against live subprocesses: the
authority's source-mode command must actually boot this runtime's CLI, and the
run-module dispatch verb must really dispatch an allowlisted module and really
refuse everything else. No shape is asserted that is not also proven runnable.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from ..runtime_exec import (
    CLI_MODULE,
    DISPATCHABLE_MODULES,
    RUN_MODULE_VERB,
    is_module_invocation,
    module_command,
    self_command,
)


def test_self_command_source_shape() -> None:
    """From source the authority renders the venv interpreter plus the CLI module."""
    assert self_command("serve") == [sys.executable, "-m", CLI_MODULE, "serve"]
    assert self_command() == [sys.executable, "-m", CLI_MODULE]


def test_module_command_source_shape_for_every_allowlisted_module() -> None:
    """Every allowlisted module renders the plain ``-m`` invocation from source."""
    for module in DISPATCHABLE_MODULES:
        assert module_command(module) == [sys.executable, "-m", module]


def test_module_command_refuses_unlisted_module() -> None:
    """A module outside the allowlist cannot even be rendered."""
    with pytest.raises(ValueError, match="not dispatchable"):
        module_command("os")


def test_is_module_invocation_accepts_exactly_both_authority_shapes() -> None:
    """The admission key matches the source and frozen shapes and nothing else."""
    module = "vaultspec_a2a.protocols.mcp.authoring_stdio"
    assert is_module_invocation(["-m", module], module)
    assert is_module_invocation([RUN_MODULE_VERB, module], module)
    assert not is_module_invocation(["-m", "os"], module)
    assert not is_module_invocation(["-m", module, "extra"], module)
    assert not is_module_invocation(None, module)
    assert not is_module_invocation([], module)


def test_self_command_really_boots_the_cli() -> None:
    """The rendered self-invocation is runnable, not just well-shaped."""
    result = subprocess.run(
        [*self_command(), "--version"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "vaultspec-a2a" in result.stdout


def test_run_module_verb_refuses_unlisted_module_loudly() -> None:
    """The dispatch verb fails closed on a hand-assembled unlisted module."""
    result = subprocess.run(
        [*self_command(), RUN_MODULE_VERB, "os"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "not dispatchable" in result.stderr


def test_run_module_verb_dispatches_vaultspec_core() -> None:
    """The dispatch verb really runs an allowlisted module as ``__main__``.

    ``vaultspec_core --version`` is the cheapest allowlisted invocation with an
    observable, service-free result; its exit proves argv threading through the
    runpy dispatch, not just import success.
    """
    result = subprocess.run(
        [*self_command(), RUN_MODULE_VERB, "vaultspec_core", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
