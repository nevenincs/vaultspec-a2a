"""Real-artifact guard for the release proposal and publication boundary."""

from __future__ import annotations

import json
import re
import tomllib
from typing import Any, cast

import yaml

from dev.paths import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _workflow(name: str) -> dict[str, Any]:
    loaded = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast("dict[str, Any]", loaded)


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML 1.1 treats the plain scalar `on` as boolean true.
    value = workflow.get("on", workflow.get(True))
    assert isinstance(value, dict)
    return cast("dict[str, Any]", value)


def test_release_please_owns_reviewable_version_proposals() -> None:
    """Keep release proposals reviewed and their version the one released."""
    config = json.loads((REPO_ROOT / "release-please-config.json").read_text("utf-8"))
    manifest = json.loads(
        (REPO_ROOT / ".release-please-manifest.json").read_text("utf-8")
    )
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text("utf-8"))
    package = config["packages"]["."]

    assert package["release-type"] == "python"
    assert package["package-name"] == "vaultspec-a2a"
    assert manifest["."] == project["project"]["version"]

    steps = _workflow("release-please.yml")["jobs"]["release-please"]["steps"]
    assert re.fullmatch(
        r"googleapis/release-please-action@[0-9a-f]{40}", steps[0]["uses"]
    )
    for step in steps[1:]:
        assert step["if"] == "steps.release.outputs.pr"


def test_nothing_starts_itself_from_a_tag_or_a_release() -> None:
    """No workflow may be started by a tag push or by a release event.

    The tag and the draft release are created seconds apart by the cut, and the
    cut then dispatches the one lane that fills the draft. A workflow listening
    for either event would start a second copy of that lane for the same tag,
    and the two would race to attach the same archive names to the same draft.
    An unfiltered `push` is the quiet way in, because it matches tag refs too;
    every push trigger therefore names the branches it wants.

    Mutation proof: restoring `push: tags: ['v*.*.*']` to release.yml makes this
    fail on that workflow's tag trigger; removing it again makes this pass.
    """
    for path in sorted(WORKFLOWS.glob("*.yml")):
        triggers = _triggers(_workflow(path.name))
        assert "release" not in triggers, (
            f"{path.name} runs on the release event; the release cut starts "
            f"every release lane by dispatch so the same tag cannot be built twice"
        )
        if "push" not in triggers:
            continue
        push: dict[str, Any] = cast("dict[str, Any] | None", triggers["push"]) or {}
        assert "tags" not in push, (
            f"{path.name} runs on a tag push; the release cut dispatches the "
            f"release lane with the tag it has just proved"
        )
        assert push.get("branches"), (
            f"{path.name} declares a `push` trigger without `branches`, which "
            f"matches tag refs as well as branches"
        )


def test_release_proves_tag_and_publishes_complete_cohort_last() -> None:
    """Permit exact tag publication while refusing partial artifact sets."""
    workflow = _workflow("release.yml")
    triggers = _triggers(workflow)
    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"] == {
        "tag": {
            "description": "Existing release tag to build and upload (e.g. v0.2.0)",
            "required": True,
            "type": "string",
        }
    }
    jobs = workflow["jobs"]
    assert "prepare" not in jobs
    assert jobs["health"]["uses"] == "./.github/workflows/test.yml"
    assert jobs["health"]["with"]["ref"] == "${{ inputs.tag || github.ref }}"
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
    assert "checksum mismatch" in steps[-4]["run"]
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


def test_release_qualifies_native_artifacts_without_container_publication() -> None:
    """Shipping the native runtime must not require an application Docker image."""
    release = _workflow("release.yml")
    assert set(release["jobs"]) == {"health", "build", "provenance", "publish"}
    build_steps = release["jobs"]["build"]["steps"]
    lifecycle = next(
        step
        for step in build_steps
        if step.get("run") == "bash scripts/prove_artifact_lifecycle.sh"
    )
    assert lifecycle.get("if") is None
    assert lifecycle.get("continue-on-error", False) is False
    assert not (WORKFLOWS / "deploy-containers.yml").exists()
    for path in WORKFLOWS.glob("*.yml"):
        workflow = _workflow(path.name)
        permissions = workflow.get("permissions", {})
        assert permissions.get("packages") != "write", path.name
        for job in workflow["jobs"].values():
            assert job.get("permissions", {}).get("packages") != "write", path.name
            for step in job.get("steps", []):
                command = step.get("run", "")
                assert not re.search(
                    r"\bjust (?:ci-worker-image|release-containers|"
                    r"deploy-containers)\b",
                    command,
                ), path.name


def test_full_validation_preserves_native_certification() -> None:
    """Keep the native product gate after retiring application Compose checks."""
    jobs = _workflow("test.yml")["jobs"]
    assert "compose-regression" not in jobs
    assert "worker-image" not in jobs
    integration = jobs["native-integration"]
    assert integration["needs"] == "test"
    assert integration.get("if") is None
    assert integration.get("continue-on-error", False) is False
    assert "docker-rootless" in integration["runs-on"]
    fixture_tools = next(
        step
        for step in integration["steps"]
        if step.get("run") == "just deps-docker-ci"
    )
    assert fixture_tools.get("if") is None
    assert fixture_tools.get("continue-on-error", False) is False
    native_proof = next(
        step
        for step in integration["steps"]
        if step.get("run") == "just test-native-integration"
    )
    assert native_proof.get("if") is None
    assert native_proof.get("continue-on-error", False) is False
    assert integration["steps"].index(fixture_tools) < integration["steps"].index(
        native_proof
    )
    desktop = jobs["desktop-certification"]
    assert desktop["needs"] == "test"
    assert desktop.get("continue-on-error", False) is False
    assert desktop.get("if") is None
    proof = next(
        step
        for step in desktop["steps"]
        if "just test-service-path src/vaultspec_a2a/desktop_tests/"
        in step.get("run", "")
    )
    assert proof.get("continue-on-error", False) is False
    assert proof.get("if") is None
