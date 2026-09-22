"""Real-artifact guard for the release proposal and publication boundary."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> dict[str, Any]:
    loaded = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML 1.1 treats the plain scalar `on` as boolean true.
    value = workflow.get("on", workflow.get(True))
    assert isinstance(value, dict)
    return value


def test_release_please_owns_reviewable_version_proposals() -> None:
    """Keep release proposals reviewed and publication separately dispatched."""
    config = json.loads((ROOT / "release-please-config.json").read_text("utf-8"))
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text("utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    package = config["packages"]["."]

    assert package["release-type"] == "python"
    assert package["package-name"] == "vaultspec-a2a"
    assert package["draft"] is True
    assert manifest["."] == project["project"]["version"]

    workflow = _workflow("release-please.yml")
    assert _triggers(workflow) == {"push": {"branches": ["main"]}}
    assert workflow["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "actions": "write",
    }
    steps = workflow["jobs"]["release-please"]["steps"]
    assert re.fullmatch(
        r"googleapis/release-please-action@[0-9a-f]{40}", steps[0]["uses"]
    )
    assert "gh workflow run merge-gate.yml" in steps[1]["run"]
    assert "gh workflow run release.yml" in steps[2]["run"]


def test_release_proves_tag_and_publishes_complete_cohort_last() -> None:
    """Prevent an implicit tag push or partial artifact set from publishing."""
    workflow = _workflow("release.yml")
    assert set(_triggers(workflow)) == {"workflow_dispatch"}
    jobs = workflow["jobs"]
    assert jobs["health"]["uses"] == "./.github/workflows/test.yml"
    assert jobs["health"]["with"]["ref"] == "${{ inputs.tag }}"
    assert jobs["build"]["needs"] == "health"
    assert jobs["provenance"]["needs"] == "build"
    assert jobs["provenance"]["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
    }
    assert jobs["publish"]["needs"] == ["build", "provenance"]
    assert jobs["publish"]["permissions"] == {"contents": "write"}

    steps = jobs["publish"]["steps"]
    assert [step["name"] for step in steps[-2:]] == [
        "Verify attached archive provenance",
        "Publish the complete release",
    ]
    upload = steps[-3]["run"]
    assert 'gh release upload "$RAW_TAG" "${members[@]}"' in upload
    assert "members/*" not in upload
    assert "gh attestation verify" in steps[-2]["run"]
    assert 'gh release edit "$RAW_TAG" --draft=false' in steps[-1]["run"]


def test_full_validation_checks_out_the_requested_release_ref() -> None:
    """Require the broad post-merge workflow, not the fast PR subset, for release."""
    workflow = _workflow("test.yml")
    assert workflow["name"] == "Full Validation"
    triggers = _triggers(workflow)
    assert triggers["workflow_call"]["inputs"]["ref"]["required"] is True
    for job in workflow["jobs"].values():
        steps = job.get("steps", [])
        checkout = next(
            (
                step
                for step in steps
                if str(step.get("uses", "")).startswith("actions/checkout@")
            ),
            None,
        )
        if checkout is not None:
            assert checkout["with"]["ref"] == "${{ inputs.ref || github.sha }}"


def test_merge_gate_accepts_an_explicit_release_ref() -> None:
    """Bind reusable release validation to the immutable requested tag."""
    workflow = _workflow("merge-gate.yml")
    triggers = _triggers(workflow)
    assert triggers["workflow_call"]["inputs"]["ref"]["required"] is True
    checkout = workflow["jobs"]["basic"]["steps"][0]
    assert checkout["with"]["ref"] == "${{ inputs.ref || github.sha }}"
