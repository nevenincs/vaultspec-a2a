"""Real-artifact guard for the declarative CI ownership boundary."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

runner = import_module("dev.runner")
toolchain = import_module("dev.toolchain")
Cmd = runner.Cmd
Ref = runner.Ref
AUDIT = toolchain.AUDIT
CI = toolchain.CI
LINT = toolchain.LINT
PYTHON_PATHS = toolchain.PYTHON_PATHS
find_verb = toolchain.find_verb

# The dimensions still carried as advisory sentinels. A dimension leaves this
# tuple when it graduates into `lint all` and its sentinel step goes with it -
# `imports` and `type-platforms` have both done so. The structural assertions on
# `type-platforms` below still hold it to its shape; it is only no longer
# advisory.
STRICT_SENTINELS = (
    "type-strict",
    "complexity",
    "cyclomatic",
    "shape",
    "limits",
    "nesting",
    "size",
)
PLATFORMS = ("linux", "darwin", "win32")


def _ci_recipe_lines() -> list[str]:
    """Return the tracked root ``ci`` recipe body exactly as written."""
    lines = (ROOT / "Justfile").read_text(encoding="utf-8").splitlines()
    start = lines.index("ci:") + 1
    body: list[str] = []
    for line in lines[start:]:
        if not line.strip():
            break
        body.append(line)
    return body


def _test_job_steps() -> list[dict[str, object]]:
    """Read the tracked test-job steps through the production YAML parser."""
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    )
    return workflow["jobs"]["test"]["steps"]


def _run_steps(steps: list[dict[str, object]], command: str) -> list[dict[str, object]]:
    """Return live workflow steps whose complete command equals ``command``."""
    return [step for step in steps if step.get("run") == command]


def test_ci_contract() -> None:
    """Keep the root facade, registry, and hosted CI declarations in agreement."""
    assert _ci_recipe_lines() == [
        "    uv run --isolated --no-project python -m dev ci all"
    ]

    lint = find_verb("lint")
    audit = find_verb("audit")
    test = find_verb("test")
    ci = find_verb("ci")
    assert lint is LINT
    assert audit is AUDIT
    assert test is not None
    assert ci is CI

    steps = _test_job_steps()
    assert len(_run_steps(steps, "just ci")) == 1
    # Bind the run text rather than re-indexing: an isinstance check on
    # ``step.get("run")`` does not narrow a second ``step["run"]`` lookup, so the
    # str methods below were being read off ``object``.
    sentinel_runs = [
        run
        for step in steps
        if isinstance(run := step.get("run"), str) and run.startswith("just lint ")
    ]
    assert (
        tuple(run.removeprefix("just lint ") for run in sentinel_runs)
        == STRICT_SENTINELS
    )

    lint_all = lint.find("all")
    assert lint_all is not None
    lint_all_targets = tuple(
        step.target for step in lint_all.steps if isinstance(step, Ref)
    )

    for name in STRICT_SENTINELS:
        target = lint.find(name)
        assert target is not None
        assert not target.advisory
        workflow_steps = _run_steps(steps, f"just lint {name}")
        assert len(workflow_steps) == 1
        workflow_step = workflow_steps[0]
        assert workflow_step.get("if") == "${{ !cancelled() }}"
        assert workflow_step.get("continue-on-error") is (name not in lint_all_targets)

    duplication = audit.find("duplication")
    assert duplication is not None
    assert duplication.advisory
    assert "duplication" not in lint_all_targets
    duplication_steps = _run_steps(steps, "just audit duplication")
    assert len(duplication_steps) == 1
    assert duplication_steps[0].get("if") == "${{ !cancelled() }}"
    assert duplication_steps[0].get("continue-on-error") is True

    type_platforms = lint.find("type-platforms")
    assert type_platforms is not None
    assert type_platforms.keep_going
    assert len(type_platforms.steps) == len(PLATFORMS)
    # Filter-then-compare-length rather than ``all(isinstance(...))``: it asserts
    # the identical property, and unlike the all() form it NARROWS, so every
    # ``.argv`` below is read off Cmd instead of the step union.
    cmd_steps = [step for step in type_platforms.steps if isinstance(step, Cmd)]
    assert len(cmd_steps) == len(type_platforms.steps)
    assert (
        tuple(step.argv[step.argv.index("--python-platform") + 1] for step in cmd_steps)
        == PLATFORMS
    )
    assert all(step.argv[-len(PYTHON_PATHS) :] == PYTHON_PATHS for step in cmd_steps)
    for platform, step in zip(PLATFORMS, cmd_steps, strict=True):
        assert step.argv[:13] == (
            "uv",
            "run",
            "--no-sync",
            "--frozen",
            "--no-default-groups",
            "--group",
            "tooling",
            "python",
            "-m",
            "ty",
            "check",
            "--python-platform",
            platform,
        )

    ci_all = ci.find("all")
    assert ci_all is not None
    ci_steps = ci_all.steps
    vault_index = next(
        index
        for index, step in enumerate(ci_steps)
        if isinstance(step, Cmd)
        and step.argv[-4:] == ("vaultspec-core", "vault", "check", "all")
    )
    harness_index = next(
        index
        for index, step in enumerate(ci_steps)
        if isinstance(step, Cmd) and step.argv[-2:] == ("test", "harness")
    )
    unit_index = next(
        index
        for index, step in enumerate(ci_steps)
        if isinstance(step, Cmd) and step.argv[-2:] == ("test", "unit")
    )
    assert vault_index < harness_index < unit_index
