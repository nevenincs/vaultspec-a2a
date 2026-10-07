"""Contract checks for A2A's release-please proposal and cut.

The proposal path keeps the release pull request on main's newest head and
creates nothing. The dispatched cut is the single release authority: it proves
the proposal's head with the full merge gate, merges it, tags it, and starts the
release lane. These checks cover that boundary locally because exercising it
would create an irreversible tag.
"""

from __future__ import annotations

import json
import re
import tomllib
from typing import Any, cast

import yaml

from dev.paths import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
RELEASE_PLEASE_ACTION = (
    "googleapis/release-please-action@45996ed1f6d02564a971a2fa1b5860e934307cf7"
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
        (REPO_ROOT / "release-please-config.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (REPO_ROOT / ".release-please-manifest.json").read_text(encoding="utf-8")
    )
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = config["packages"]["."]
    lock_package = next(
        package
        for package in tomllib.loads(
            (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
        )["package"]
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
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## \[[0-9]+\.[0-9]+\.[0-9]+\].*$", changelog, re.MULTILINE)

    assert headings[-3:] == [
        "## [0.3.0](https://github.com/nevenincs/vaultspec-a2a/compare/"
        "v0.2.0...v0.3.0) (2026-08-02)",
        "## [0.2.0](https://github.com/nevenincs/vaultspec-a2a/compare/"
        "v0.1.0...v0.2.0) (2026-07-25)",
        "## [0.1.0](https://github.com/nevenincs/vaultspec-a2a/releases/tag/"
        "v0.1.0) (2026-07-24)",
    ]
    version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    assert headings[0].startswith(f"## [{version}](")
    assert changelog.index(headings[0]) > changelog.index("# Changelog")
    assert "prepared releases are inserted" not in changelog


def test_the_release_is_held_as_a_draft_until_the_lane_publishes_it() -> None:
    """release-please must create the release unpublished, and its tag anyway.

    A release cannot be filled in after it is visible, so the release object is
    created as a draft and published by the lane that has proved it. `draft` is
    only half of that: GitHub creates no git tag for a draft release, and every
    job in the lane checks out the tag for its source, so `force-tag-creation`
    is what gives the build a ref to build from.

    Mutation proof: setting `draft` to false in the configuration makes this fail
    on the draft requirement; restoring it makes this pass.
    """
    package = json.loads(
        (REPO_ROOT / "release-please-config.json").read_text(encoding="utf-8")
    )["packages"]["."]

    assert package.get("draft") is True, (
        "release-please must create the release as a draft; a visible release "
        "cannot receive the archives that justify it"
    )
    assert package.get("force-tag-creation") is True, (
        "a draft release creates no git tag, and the whole lane builds from the "
        "tag - release-please must force it into existence"
    )

    publish = _workflow("release.yml")["jobs"]["publish"]
    steps = [str(step.get("name")) for step in publish["steps"]]
    assert steps[-1] == "Publish the complete release", (
        "the draft must be flipped by the lane's last step, after every archive "
        "is attached and its provenance verified"
    )


def _release_please_jobs() -> dict[str, dict[str, Any]]:
    """Return the release-please workflow's jobs, parsed as plain strings."""
    return cast("dict[str, dict[str, Any]]", _workflow("release-please.yml")["jobs"])


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one job's steps."""
    return cast("list[dict[str, Any]]", job.get("steps", []))


def test_the_proposal_keeps_up_and_never_releases() -> None:
    """The push path refreshes the pull request and dispatches its own gate.

    `always-update` is what keeps the proposal on main's newest head, so a cut
    never has to wait for a rebuild. The proposal itself creates nothing: the
    action runs with `skip-github-release`, and the merge gate is dispatched
    last so it validates the lockfile commit the step before it pushed.

    Mutation proof: removing `always-update` from the configuration makes this
    fail on that setting; restoring it makes this pass.
    """
    config = json.loads(
        (REPO_ROOT / "release-please-config.json").read_text(encoding="utf-8")
    )
    assert config.get("always-update") is True, (
        "without `always-update` the proposal branch lags main, and the cut "
        "refuses a candidate that is behind"
    )

    workflow = _workflow("release-please.yml")
    assert set(workflow["on"]) == {"push", "workflow_dispatch"}
    assert workflow["on"]["push"] == {"branches": ["main"]}
    assert workflow["permissions"] == {"contents": "read"}, (
        "the release lane's write scopes belong to the jobs that use them, not "
        "to every job in the file"
    )

    proposal = _release_please_jobs()["release-please"]
    assert proposal["if"] == "github.event_name == 'push'"
    assert proposal["name"] == "Build: Release proposal (Linux)"
    steps = _steps(proposal)
    action = next(step for step in steps if step.get("id") == "release")
    assert action["uses"] == RELEASE_PLEASE_ACTION
    assert action["with"]["skip-github-release"] == "true"
    assert "token" not in action["with"]

    by_name = {str(step.get("name")): step for step in steps}
    refresh = by_name["Refresh the release branch lockfile"]["run"]
    assert refresh.index("just deps-lock") < refresh.index("just hooks-bootstrap")
    assert refresh.index("just hooks-bootstrap") < refresh.index("git commit")
    dispatch = by_name["Dispatch the merge gate for the release pull request"]
    assert str(dispatch["run"]).startswith("gh workflow run merge-gate.yml ")
    assert steps[-1] is dispatch, (
        "the gate dispatch must be last so it validates the refreshed lock"
    )


def test_only_the_dispatched_cut_creates_a_release() -> None:
    """The cut is the one release authority, and it starts exactly one lane.

    The proposal path refreshes the release pull request and never releases. A
    maintainer dispatches the cut, which proves, merges and tags, then
    dispatches the release lane, which publishes the draft last. If the lane
    also listened for the tag push, or the proposal path could release, the same
    release could race an unproven run through publication.

    Mutation proof: dropping `skip-github-release` from the proposal step makes
    this fail on the release-creating jobs; restoring it makes this pass.
    """
    lane = _workflow("release.yml")
    triggers = cast("dict[str, Any]", lane["on"])
    assert set(triggers) == {"workflow_dispatch"}, (
        "release.yml must be dispatch-only; the release cut owns release "
        f"initiation, but it also declares {sorted(triggers)}"
    )
    tag = cast("dict[str, str]", triggers["workflow_dispatch"]["inputs"]["tag"])
    assert tag["required"] == "true", "release.yml must require the release tag"

    creators = sorted(
        job_id
        for job_id, job in _release_please_jobs().items()
        for step in _steps(job)
        if str(step.get("uses", "")).startswith("googleapis/release-please-action@")
        and cast("dict[str, str]", step.get("with", {})).get("skip-github-release")
        != "true"
    )
    assert creators == ["cut"], (
        "only the dispatched cut may create a release; the proposal path must "
        f"run with `skip-github-release`, but these jobs can release: {creators}"
    )

    authority = (WORKFLOWS / "release-please.yml").read_text(encoding="utf-8")
    dispatch = (
        'gh workflow run release.yml --repo "${GITHUB_REPOSITORY}" '
        '--ref main -f "tag=${TAG}"'
    )
    assert dispatch in authority, (
        "the cut no longer dispatches the release lane with its immutable tag"
    )
    assert re.findall(r"gh workflow run (\S+)", authority) == [
        "merge-gate.yml",
        "release.yml",
    ], "the cut starts the release lane and nothing else"


def test_the_release_is_proven_before_anything_is_tagged() -> None:
    """The cut merges and tags only the head the full merge gate passed.

    A release tag cannot be deleted, so the proof comes before it. The cut waits
    on the merge gate called on the candidate's exact head, carries no condition
    that could override that success, merges only that head, and refuses a
    merged tree that differs from the proven one before release-please creates
    anything.

    Mutation proof: removing `prove-gate` from the cut's `needs` makes this fail
    on the gate dependency; restoring it makes this pass.
    """
    jobs = _release_please_jobs()
    prove = jobs["prove-gate"]
    assert prove["uses"] == "./.github/workflows/merge-gate.yml"
    assert cast("dict[str, str]", prove["with"])["ref"] == (
        "${{ needs.candidate.outputs.sha }}"
    ), "the release gate must prove the candidate's exact head"

    cut = jobs["cut"]
    assert "prove-gate" in cast("list[str]", cut["needs"]), (
        "the cut must wait on the release gate"
    )
    assert "if" not in cut, (
        "a condition on the cut would override the default success check and "
        "let a failed gate tag a release"
    )
    steps = _steps(cut)
    names = [str(step.get("name")) for step in steps]
    merge = names.index("Merge the proven release pull request")
    create = names.index("Create the release for the merged proposal")
    require = names.index("Require the tag on the proven commit")
    assert merge < create < require, (
        "the cut must merge, then create the release, then prove its tag"
    )
    merge_run = str(steps[merge]["run"])
    assert '--match-head-commit "${SHA}"' in merge_run, (
        "the cut must merge only the head the gate proved"
    )
    assert "tree.sha" in merge_run, (
        "the cut must refuse a merged tree that differs from the proven tree"
    )
    assert (
        cast("dict[str, str]", steps[require]["env"])["COMMIT"]
        == "${{ steps.merge.outputs.commit }}"
    ), "the tag check must compare against the commit the merge produced"


def test_a_release_this_token_cannot_tag_is_named() -> None:
    """A release blocked by a workflow change diagnoses itself by tag.

    The default token holds no `workflows` permission, so GitHub refuses a tag
    or release targeting a commit whose workflow files differ from the branch
    head. release-please then fails with an API error naming neither the tag nor
    the cause, and no rerun can finish it. The diagnosis step derives the tag the
    way the configuration does and says which workflow files moved.

    Mutation proof: changing the derived tag from `v${version}` to a
    component-prefixed form makes this fail on the tag derivation; restoring it
    makes this pass.
    """
    package = json.loads(
        (REPO_ROOT / "release-please-config.json").read_text(encoding="utf-8")
    )["packages"]["."]
    assert package["include-component-in-tag"] is False, (
        "the diagnosis and the recovery runbook both derive a bare `v<version>`"
    )

    cut = _release_please_jobs()["cut"]
    diagnose = next(
        step
        for step in _steps(cut)
        if step.get("name") == "Name a release this token cannot tag"
    )
    assert diagnose["if"] == "failure() && steps.release.outcome == 'failure'", (
        "the diagnosis must run only when the release creation itself failed"
    )
    script = str(diagnose["run"])
    assert 'tag="v${version}"' in script, (
        "the diagnosis must derive the tag release-please would have created; a "
        "component-prefixed tag names a ref this repository never creates"
    )
    assert ".release-please-manifest.json?ref=${sha}" in script, (
        "the version must be read from the manifest at the merged commit"
    )
    assert ".github/workflows/" in script, (
        "the diagnosis must name the workflow files that block the tag"
    )
    assert "RUNBOOK" in cast("dict[str, str]", diagnose["env"]), (
        "the diagnosis must point at the credentialed recovery runbook"
    )
