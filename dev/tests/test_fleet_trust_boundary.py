"""Only a trusted author's code reaches the self-hosted fleet.

Every runner this repository uses is self-hosted, which `dev/ci_contract.py`
enforces separately. So a pull request that starts any job at all runs on
hardware the maintainer owns, and "which pull requests may start a job" is the
whole access-control question.

The answer is one clause, written identically in every repository of the
fleet: the pull request comes from a branch of this repository, and its author
is the owner, a collaborator, or the release App that opens the release pull
request. A `ci:full` label additionally counts only when a user - never a bot -
applied it. Forks, outside contributors, Dependabot (whose `author_association`
is CONTRIBUTOR) and every other bot start nothing. A fork's pull request runs
the fork's own copy of these files, so the fork clause only backs up the
repository's approval requirement for outside contributors; for every other
author the clause is the control itself.

The clauses are written as plain equality rather than through `contains` over a
parsed list so that the same string appears in every repository and so that an
expression evaluator can decide it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast

import yaml

from dev.paths import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path

WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: The bot the release App acts as. It opens the release pull request, which
#: must run the required gate like a maintainer's.
RELEASE_BOT = "nevenincs-release[bot]"

#: The pull request authors whose code may reach the fleet, byte-identical
#: across the fleet. This is a personal account, so there are no organisation
#: members: MEMBER is not here, and neither is CONTRIBUTOR, which is what
#: Dependabot's pull requests carry.
TRUSTED_AUTHOR = (
    "(github.event.pull_request.author_association == 'OWNER' || "
    "github.event.pull_request.author_association == 'COLLABORATOR' || "
    f"github.event.pull_request.user.login == '{RELEASE_BOT}')"
)

#: Applying a label takes triage rights; a bot applying `ci:full` does not count.
LABEL_BY_USER = "github.event.sender.type == 'User'"

#: The label that asks for one more full run of a trusted pull request.
FULL_LABEL = "ci:full"

#: Reached only when the fork's own copy of a workflow is not the one running.
SAME_REPOSITORY = "github.event.pull_request.head.repo.full_name == github.repository"

#: The sole required status check, and the name the verdict job reports under
#: whenever the trust clause withholds it instead.
REQUIRED_CHECK = "Check: Merge gate (Linux)"
WITHHELD_CHECK = "Admission withheld (Linux)"
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


def _flat(expression: object) -> str:
    """Return *expression* with its whitespace runs collapsed to one space."""
    return " ".join(str(expression).split())


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


def test_every_pull_request_job_carries_the_fleet_trust_clause() -> None:
    """No job a pull request can start reaches the fleet without the clause.

    Every runner is self-hosted, so every job in a pull-request workflow - the
    verdict job included - must carry the same-repository clause and the
    fleet's exact trusted-author clause, and a workflow that listens for labels
    must admit only `ci:full`, and only from a user.

    Mutation proof: dropping the release-bot login term from `migrate`'s
    condition in migrations.yml makes this fail on the trusted-author assertion
    naming that job; deleting the `sender.type == 'User'` term from `basic` in
    merge-gate.yml makes it fail on the label assertion naming that job;
    restoring each makes this pass.
    """
    checked: list[str] = []
    for path in _pull_request_workflows():
        workflow = _workflow(path)
        events = cast("dict[str, Any]", workflow["on"]["pull_request"] or {})
        labelled = "labeled" in cast("list[str]", events.get("types", []))
        for job_id, job in cast("dict[str, Any]", workflow["jobs"]).items():
            condition = _flat(job.get("if", ""))
            where = f"`{job_id}` in {path.name}"
            assert SAME_REPOSITORY in condition, (
                f"{where} would run a fork's code on the self-hosted fleet"
            )
            assert TRUSTED_AUTHOR in condition, (
                f"{where} lacks the fleet's exact trusted-author clause, so it "
                f"either admits an author the fleet refuses or refuses the "
                f"release App"
            )
            # The verdict job measures nothing; it must judge every trusted
            # event, an unrelated label included, so it carries no label term.
            if labelled and (path.name, job_id) != VERDICT_JOB:
                assert f"github.event.label.name == '{FULL_LABEL}'" in condition, (
                    f"{where} would be started by any label, not only `{FULL_LABEL}`"
                )
                assert LABEL_BY_USER in condition, (
                    f"{where} would let a bot's `{FULL_LABEL}` label start it"
                )
            checked.append(where)
    assert checked, "no pull-request job was examined, so this guard proved nothing"


def test_no_condition_admits_another_author_or_bot() -> None:
    """The clause is the whole allowance: no wider association, no other bot.

    A term appended beside the clause - `MEMBER`, `CONTRIBUTOR`, or a second
    bot login such as Dependabot's - widens the rule while the clause itself
    stays intact, so the assertion above would still pass.

    Mutation proof: appending `|| github.actor == 'dependabot[bot]'` to
    `migrate`'s condition in migrations.yml makes this fail on the bot-login
    assertion naming that job; removing it makes this pass.
    """
    for path in _pull_request_workflows():
        jobs = cast("dict[str, Any]", _workflow(path)["jobs"])
        for job_id, job in jobs.items():
            expressions = _flat(f"{job.get('if', '')} {job.get('name', '')}")
            where = f"`{job_id}` in {path.name}"
            for association in ("MEMBER", "CONTRIBUTOR", "NONE", "FIRST_TIME"):
                assert f"'{association}" not in expressions, (
                    f"{where} admits {association}, which the fleet never trusts"
                )
            logins = set(re.findall(r"'([^']+\[bot\])'", expressions))
            assert logins <= {RELEASE_BOT}, (
                f"{where} admits {sorted(logins - {RELEASE_BOT})}; the release "
                f"App is the only bot that may reach the fleet"
            )


def test_a_push_reaches_the_fleet_only_from_main() -> None:
    """A branch push never starts a job; only main's history does.

    Dependabot and every bot that can write a branch of this repository raise
    `push` events for it. A push trigger that matches any branch but main
    therefore runs a bot's tree on the fleet with no pull-request clause in the
    way.

    Mutation proof: widening migrations.yml's push trigger to
    `branches: ['**']` makes this fail naming that workflow; restoring
    `branches: [main]` makes this pass.
    """
    for path in sorted(WORKFLOWS.glob("*.yml")):
        triggers = _workflow(path)["on"]
        if "push" not in triggers:
            continue
        push = cast("dict[str, Any]", triggers["push"] or {})
        assert push.get("branches") == ["main"], (
            f"{path.name} runs on pushes to {push.get('branches')}; a bot's "
            f"branch push would reach the self-hosted fleet"
        )


def test_the_merge_gate_runs_only_for_pull_requests() -> None:
    """The required check is reported only by the pull request's own events.

    A dispatched or called run of the gate links its checks to no pull request,
    so it can never satisfy the ruleset, and a workflow that dispatches it is a
    workaround for a pull request that cannot run its own gate.

    Mutation proof: adding a `workflow_dispatch` trigger to merge-gate.yml makes
    this fail on the trigger set; removing it makes this pass.
    """
    name, _ = VERDICT_JOB
    triggers = cast("dict[str, Any]", _workflow(WORKFLOWS / name)["on"])
    assert set(triggers) == {"pull_request"}, (
        f"{name} must start only from pull-request events, but also declares "
        f"{sorted(set(triggers) - {'pull_request'})}"
    )
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert f"gh workflow run {name}" not in text, (
            f"{path.name} dispatches {name}; its checks would attach to no pull request"
        )
        assert f"uses: ./.github/workflows/{name}" not in text, (
            f"{path.name} calls {name}; its checks would attach to no pull request"
        )


def test_a_withheld_verdict_never_reports_the_required_check() -> None:
    """The required check is never reported by a skipped job.

    A required check whose job is skipped counts as passed. So the verdict job
    carries the trust rule in its condition AND in its name: when the clause
    refuses a pull request the job is skipped as `Admission withheld (Linux)`,
    the required check stays expected, and the commit cannot merge. For a
    trusted pull request it runs on every event, and a label that started
    nothing finds this check's own earlier success on the same commit.

    Mutation proof: replacing the gate's name expression with the literal
    `Check: Merge gate (Linux)` makes this fail on the name assertion; restoring
    it makes this pass.
    """
    name, job_id = VERDICT_JOB
    jobs = cast("dict[str, Any]", _workflow(WORKFLOWS / name)["jobs"])
    gate = jobs[job_id]
    admitted = f"({SAME_REPOSITORY} && {TRUSTED_AUTHOR})"
    assert _flat(gate["name"]) == (
        f"${{{{ {admitted} && '{REQUIRED_CHECK}' || '{WITHHELD_CHECK}' }}}}"
    ), (
        "the verdict job must report the required check only when the trust "
        "clause admits the pull request, and another name when it withholds it"
    )
    assert _flat(gate["if"]) == f"always() && {SAME_REPOSITORY} && {TRUSTED_AUTHOR}", (
        "the verdict must run for every trusted event; `always()` keeps a "
        "failed measuring job from skipping it"
    )
    for other_id, other in jobs.items():
        if other_id != job_id:
            assert REQUIRED_CHECK not in str(other.get("name", "")), (
                f"`{other_id}` also reports {REQUIRED_CHECK}"
            )

    steps = {str(step.get("name")): step for step in gate["steps"]}
    script = str(steps["Judge the required checks"]["run"])
    assert "commits/$HEAD_SHA/check-runs?check_name=Check:%20Merge%20gate" in script, (
        "an earlier verdict counts only when it was reached on the same commit, "
        "and only under the required check's exact name"
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
