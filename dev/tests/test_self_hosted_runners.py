"""Every workflow job is placed on the self-hosted fleet.

A job whose ``runs-on`` omits the ``self-hosted`` label is eligible for a
GitHub-hosted machine, which this repository does not use. A matrix-driven
``runs-on`` is resolved through each ``include`` entry, so a single hosted leg
cannot hide behind the expression.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
MATRIX_RUNNER = "${{ matrix.runner }}"


def _labels(runs_on: object) -> list[str]:
    if isinstance(runs_on, str):
        return [runs_on]
    return [str(label) for label in cast("list[object]", runs_on)]


def _placements(job: dict[str, Any]) -> list[list[str]]:
    runs_on = job["runs-on"]
    if runs_on != MATRIX_RUNNER:
        return [_labels(runs_on)]
    include = cast("list[dict[str, Any]]", job["strategy"]["matrix"]["include"])
    return [_labels(entry["runner"]) for entry in include]


def test_every_job_runs_on_a_self_hosted_runner() -> None:
    hosted: list[str] = []
    placed = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = cast(
            "dict[str, Any]",
            yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader),
        )
        for name, job in cast("dict[str, dict[str, Any]]", workflow["jobs"]).items():
            if "uses" in job:
                # A reusable-workflow call places no runner itself; the called
                # workflow's own jobs are checked where they are declared.
                continue
            for labels in _placements(job):
                placed += 1
                if "self-hosted" not in labels:
                    hosted.append(f"{path.name}:{name} -> {labels}")
    assert placed > 0
    assert hosted == []
