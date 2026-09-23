"""Contract checks for A2A's release-please proposal lane.

The action may create a draft A2A release and its tag, but it must never chain
that event into the Dashboard-selected artifact publisher.  These checks cover
the boundary locally because exercising it would create an irreversible tag.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
RELEASE_PLEASE_ACTION = (
    "googleapis/release-please-action@5c625bfb5d1ff62eadeeb3772007f7f66fdcf071"
)


def _workflow(name: str) -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        yaml.load(
            (WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader
        ),
    )


def test_release_please_config_tracks_the_python_package_version() -> None:
    """The release PR advances its package and manifest; the lock follows."""
    config = json.loads(
        (ROOT / "release-please-config.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (ROOT / ".release-please-manifest.json").read_text(encoding="utf-8")
    )
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = config["packages"]["."]
    lock_package = next(
        package
        for package in tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))[
            "package"
        ]
        if package["name"] == project["project"]["name"]
    )

    assert package["release-type"] == "python"
    assert package["package-name"] == project["project"]["name"]
    assert manifest == {".": project["project"]["version"]}
    assert lock_package["version"] == project["project"]["version"]
    # release-please's toml updater left the lock at the old version on the
    # 0.3.1 proposal; the workflow regenerates the lock on the branch instead.
    assert "extra-files" not in package
    assert package["include-component-in-tag"] is False
    assert package["draft"] is True
    assert package["force-tag-creation"] is True
    assert package["bump-minor-pre-major"] is True
    assert package["bump-patch-for-minor-pre-major"] is True
    assert [section["type"] for section in package["changelog-sections"]] == [
        "feat",
        "fix",
        "perf",
        "docs",
        "chore",
        "ci",
        "refactor",
        "test",
    ]


def test_release_please_can_insert_the_first_pr_above_bootstrapped_history() -> None:
    """Historical headings match release-please's version-header insertion point."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## \[[0-9]+\.[0-9]+\.[0-9]+\].*$", changelog, re.MULTILINE)

    assert headings == [
        "## [0.3.0](https://github.com/nevenincs/vaultspec-a2a/compare/"
        "v0.2.0...v0.3.0) (2026-08-02)",
        "## [0.2.0](https://github.com/nevenincs/vaultspec-a2a/compare/"
        "v0.1.0...v0.2.0) (2026-07-25)",
        "## [0.1.0](https://github.com/nevenincs/vaultspec-a2a/releases/tag/"
        "v0.1.0) (2026-07-24)",
    ]
    assert changelog.index(headings[0]) > changelog.index("# Changelog")
    assert "prepared releases are inserted" not in changelog


def test_release_please_runs_only_for_main_and_uses_the_pr_gate() -> None:
    """The proposal is serialized, locked, and dispatches its required check."""
    workflow = _workflow("release-please.yml")
    merge_gate = _workflow("merge-gate.yml")
    release = workflow["jobs"]["release-please"]
    steps = release["steps"]
    action = next(step for step in steps if step.get("id") == "release")
    by_name = {step["name"]: step for step in steps}

    assert workflow["on"] == {"push": {"branches": ["main"]}}
    assert workflow["permissions"] == {
        "actions": "write",
        "contents": "write",
        "pull-requests": "write",
    }
    assert workflow["concurrency"] == {
        "group": "release-please-${{ github.ref }}",
        "cancel-in-progress": "false",
    }
    assert release["name"] == "Build: Release proposal (Linux)"
    assert release["timeout-minutes"] == "30"
    assert action["uses"] == RELEASE_PLEASE_ACTION
    assert action["with"] == {
        "config-file": "release-please-config.json",
        "manifest-file": ".release-please-manifest.json",
    }
    assert "token" not in action["with"]
    assert "just deps-lock" in by_name["Refresh the release branch lockfile"]["run"]
    dispatch = by_name["Dispatch the merge gate for the release pull request"]
    assert dispatch["run"].startswith("gh workflow run merge-gate.yml ")
    # The dispatch is last so the gate validates the refreshed lock commit.
    assert steps[-1] is dispatch
    assert "workflow_dispatch" in merge_gate["on"]
    assert merge_gate["on"]["pull_request"]["types"] == [
        "opened",
        "reopened",
        "synchronize",
        "ready_for_review",
    ]
    assert merge_gate["jobs"]["gate"]["name"] == "Check: Merge gate (Linux)"


def test_release_please_cannot_dispatch_or_weaken_the_artifact_publisher() -> None:
    """Dashboard remains the release-set selector and publication stays guarded."""
    release_please = (WORKFLOWS / "release-please.yml").read_text(encoding="utf-8")
    release = _workflow("release.yml")

    dispatched = re.findall(r"gh workflow run (\S+)", release_please)
    assert dispatched == ["merge-gate.yml"]
    assert "push" in release["on"]
    assert release["on"]["push"]["tags"] == ["v*.*.*"]
    assert "workflow_dispatch" in release["on"]
    assert release["on"]["workflow_dispatch"]["inputs"] == {
        "tag": {
            "description": "Existing release tag to build and upload (e.g. v0.2.0)",
            "required": "true",
            "type": "string",
        }
    }
    assert "prepare" not in release["jobs"]
    assert release["jobs"]["health"]["uses"] == "./.github/workflows/test.yml"
    assert release["jobs"]["build"]["needs"] == "health"
    assert release["jobs"]["provenance"]["needs"] == "build"
    assert release["jobs"]["publish"]["needs"] == ["build", "provenance"]
    assert "prepare-release" not in (ROOT / "Justfile").read_text(encoding="utf-8")
    assert not (ROOT / "scripts" / "prepare_release.py").exists()
