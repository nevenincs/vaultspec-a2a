"""Only a trusted author's code reaches the self-hosted fleet.

Every runner this repository uses is self-hosted, which `dev/ci_contract.py`
enforces separately. So a pull request that starts any job at all runs its own
tree on hardware the maintainer owns, and "which pull requests may start a job"
is the whole access-control question.

The answer has two clauses. The author must be the owner or a collaborator, or a
user - never a bot - must have applied `ci:full`, which takes triage rights. A
fork's pull request runs the fork's own copy of these files, so the fork clause
only backs up the repository's approval requirement for outside contributors;
for every other author, including Dependabot, whose `author_association` is
CONTRIBUTOR, the author clause is the control itself.

The clauses are written as plain equality rather than through `contains` over a
parsed list so that the same string appears in every repository and so that an
expression evaluator can decide it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

#: The pull request authors whose code may reach the fleet unreviewed. This is a
#: personal account, so there are no organisation members: MEMBER is not here,
#: and neither is CONTRIBUTOR, which is what Dependabot's pull requests carry.
TRUSTED_AUTHOR = (
    "(github.event.pull_request.author_association == 'OWNER' || "
    "github.event.pull_request.author_association == 'COLLABORATOR')"
)

#: Applying a label takes triage rights; a bot applying `ci:full` does not count.
LABEL_BY_USER = "github.event.sender.type == 'User'"

#: The label that asks for one full run on an otherwise untrusted commit.
FULL_LABEL = "ci:full"

#: Reached only when the fork's own copy of a workflow is not the one running.
SAME_REPOSITORY = "github.event.pull_request.head.repo.full_name == github.repository"

#: The one job that must run for every pull-request event, including a label
#: that starts nothing. A required check whose job is skipped counts as PASSED,
#: so this job cannot carry the trust rule in its condition and refuses an
#: untrusted author inside its script instead.
VERDICT_JOB = ("merge-gate.yml", "gate")


#: Events anyone can raise by writing on an issue, a pull request or a
#: discussion, mapped to the payload object whose author association decides
#: whether a job may start from them.
WRITTEN_EVENTS = {
    "issue_comment": "comment",
    "pull_request_review_comment": "comment",
    "pull_request_review": "review",
    "issues": "issue",
    "discussion": "discussion",
    "discussion_comment": "comment",
}


def _trusted(subject: str) -> str:
    """Return the trust clause over the author of *subject* in the payload."""
    return (
        f"(github.event.{subject}.author_association == 'OWNER' || "
        f"github.event.{subject}.author_association == 'COLLABORATOR')"
    )


def _workflow(path: Path) -> dict[str, Any]:
    loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict)
    return cast("dict[str, Any]", loaded)


def _pull_request_workflows() -> list[Path]:
    """Return every workflow a pull request can start."""
    return [
        path
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if "pull_request" in _workflow(path)["on"]
    ]


def test_no_workflow_runs_a_pull_request_with_the_base_repositorys_secrets() -> None:
    """`pull_request_target` is never used.

    That trigger runs with the base repository's token and secrets while the
    checkout a step asks for is the pull request's own tree, so a contributor's
    commit executes with write credentials. There is no use for it here: the
    trust rule below decides whether a pull request runs at all.

    Mutation proof: adding a `pull_request_target` trigger to claude.yml makes
    this fail naming that workflow; removing it again makes this pass.
    """
    for path in sorted(WORKFLOWS.glob("*.yml")):
        assert "pull_request_target" not in _workflow(path)["on"], (
            f"{path.name} uses pull_request_target, which runs a contributor's "
            f"tree with this repository's write token"
        )


def test_only_a_trusted_author_or_a_users_label_reaches_the_fleet() -> None:
    """Every pull-request job but the verdict carries the full trust rule.

    Every runner is self-hosted, so there is no job in a pull-request workflow
    that may start for an untrusted author. The `labeled` event is in each
    workflow's trigger list because the label clause is the only way a
    collaborator can release a run for an author the first clause refuses.

    Mutation proof: dropping the author clause from `migrate`'s condition in
    migrations.yml makes this fail naming that job; restoring it makes this pass.
    """
    checked: list[str] = []
    for path in _pull_request_workflows():
        workflow = _workflow(path)
        events = cast("dict[str, Any]", workflow["on"]["pull_request"] or {})
        assert "labeled" in cast("list[str]", events.get("types", [])), (
            f"{path.name} never sees the `{FULL_LABEL}` label, so a collaborator "
            f"has no way to release a run for an author the trust rule refuses"
        )
        for job_id, job in cast("dict[str, Any]", workflow["jobs"]).items():
            if (path.name, job_id) == VERDICT_JOB:
                continue
            condition = str(job.get("if", ""))
            where = f"`{job_id}` in {path.name}"
            assert "github.event_name != 'pull_request'" in condition, (
                f"{where} has no pull-request clause, so it either never runs "
                f"outside one or runs for everyone inside one"
            )
            assert SAME_REPOSITORY in condition, (
                f"{where} would run a fork's code on the self-hosted fleet"
            )
            assert TRUSTED_AUTHOR in condition, (
                f"{where} would run a pull request by any author on the "
                f"self-hosted fleet, Dependabot included"
            )
            assert f"github.event.label.name == '{FULL_LABEL}'" in condition, (
                f"{where} would be started by any label, not only `{FULL_LABEL}`"
            )
            assert LABEL_BY_USER in condition, (
                f"{where} would let a bot's `{FULL_LABEL}` label start it"
            )
            checked.append(where)
    assert checked, "no pull-request job was examined, so this guard proved nothing"


def test_the_gate_always_reaches_a_verdict_and_refuses_an_untrusted_author() -> None:
    """The required check is never skipped, and it names who it refused.

    A required check whose job is skipped counts as passed, so the gate runs for
    every pull-request event - an unrelated label included - and decides. A label
    that started nothing is not a failure: the gate finds its own earlier success
    on the same commit. Only when there is no such verdict does the author matter,
    and then the refusal says whose commit it is and what releases it.

    Mutation proof: deleting the untrusted-author refusal from the judgement
    makes this fail on that refusal; restoring it makes this pass.
    """
    name, job_id = VERDICT_JOB
    gate = _workflow(WORKFLOWS / name)["jobs"][job_id]
    assert gate["if"] == "always()", (
        "the required check must run for every event; a skipped required check "
        "counts as passed"
    )

    env = cast("dict[str, str]", gate["env"])
    assert env["ASSOCIATION"] == "${{ github.event.pull_request.author_association }}"
    assert env["AUTHOR"] == "${{ github.event.pull_request.user.login }}"
    assert env["HEAD_REPO"] == "${{ github.event.pull_request.head.repo.full_name }}"
    assert env["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"

    steps = {str(step.get("name")): step for step in gate["steps"]}
    script = str(steps["Judge the required checks"]["run"])

    fork = script.index('[ "$HEAD_REPO" != "$GITHUB_REPOSITORY" ]')
    assert fork < script.index("exit 0"), (
        "a fork pull request must be refused before any path can pass the gate"
    )

    verdict = script.index("check_name=Check:%20Merge%20gate%20(Linux)")
    assert "commits/$HEAD_SHA/check-runs?check_name=Check:%20Merge%20gate" in script, (
        "an earlier verdict counts only when it was reached on the same commit, "
        "and only under the required check's exact name"
    )

    marker = 'case "$ASSOCIATION" in OWNER | COLLABORATOR) ;;'
    assert marker in script, (
        "the gate no longer refuses a commit by an author who is neither the "
        "owner nor a collaborator"
    )
    untrusted = script.index(marker)
    assert verdict < untrusted, (
        "an untrusted author's commit that a collaborator's ci:full already "
        "proved must keep its verdict"
    )
    assert f"applies the {FULL_LABEL} label" in script[untrusted:], (
        "the refusal must name what releases the commit, not only that it was refused"
    )

    release = steps[f"Release the {FULL_LABEL} label"]
    assert "|| true" in str(release["run"]), (
        "a label another run already removed must not redden the gate"
    )


def test_only_a_trusted_author_can_start_a_job_by_writing_something() -> None:
    """A comment, a review or an issue starts a job only for a trusted author.

    Anyone can comment on a public issue or review a pull request, and a job
    started from that event runs on the self-hosted fleet with whatever the
    workflow grants it. The pull-request trust rule above never sees these
    workflows, so each event such a workflow listens to must name its own
    author's association - the comment's, the review's or the issue's - as the
    owner's or a collaborator's.

    Mutation proof: replacing the review author clause in claude.yml with
    `true` makes this fail naming `pull_request_review`; restoring it makes
    this pass.
    """
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = _workflow(path)
        events = [event for event in WRITTEN_EVENTS if event in workflow["on"]]
        if not events:
            continue
        for job_id, job in cast("dict[str, Any]", workflow["jobs"]).items():
            condition = " ".join(str(job.get("if", "")).split())
            where = f"`{job_id}` in {path.name}"
            for event in events:
                assert f"github.event_name == '{event}'" in condition, (
                    f"{where} does not say which condition applies to {event}, "
                    f"so it may start for anyone who raises one"
                )
                assert _trusted(WRITTEN_EVENTS[event]) in condition, (
                    f"{where} starts on {event} for an author who is neither "
                    f"the owner nor a collaborator"
                )
            assert "MEMBER" not in condition, (
                f"{where} admits MEMBER, which this personal account never "
                f"grants, so it can only widen the rule"
            )
