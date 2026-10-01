---
tags:
  - '#reference'
  - '#release-standard'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:2e9219c742d9e7aadf32efcc660863e26fc60dd106b6e3d1b11e9791b1f7fe18'
related: []
---

# `release-standard` reference: `The release and fleet-trust surface before adoption`

This record grounds the adoption of the release standard in the code that was
there. Every locator below is against the state of this repository's default
branch before the adoption branch, and every claim was read out of the file it
cites rather than inferred from a description of it. Line numbers are as of that
state and move with later edits; the file and the construct are the durable part.

## Summary

### Release initiation

`.github/workflows/release-please.yml:3` declared `on: push: branches: [main]`
and nothing else, and the action invocation at line 24 passed no
`skip-github-release`. Every commit that landed a release proposal therefore
created the tag and the release, whether or not a release was wanted, and the
commit released had been proved only as a pull request head.

The same file declared `permissions:` at line 7 with `actions: write`,
`contents: write` and `pull-requests: write` at the top level, so every job in
the file held the write scopes one job needed.

`release-please-config.json` already carried `draft: true`,
`force-tag-creation: true` and `include-component-in-tag: false`. Tags are
therefore bare `v<version>`, and a release object is created unpublished with its
git tag forced into existence anyway. `always-update` was absent, so the proposal
branch was rebuilt only when release-please happened to rewrite it, and could sit
behind main.

### Release publication

`.github/workflows/release.yml:40` declared `push: tags: ['v*.*.*']` alongside
the `workflow_dispatch` at line 42, so the lane had two doors for one tag. The
lane itself is not a relay: it freezes a PyInstaller onedir per target on a native
runner, proves the frozen tree installable and the artifact startable, archives it
with a bare-digest `.sha256` sidecar, attests provenance, refuses an incomplete
four-target cohort, and flips the draft with `gh release edit --draft=false` as
its last step. It qualifies the tag itself by calling `test.yml`, and it refuses a
tag whose version disagrees with `pyproject.toml`. So it is kept and only its tag
trigger is removed.

### Fleet trust

Every runner in every workflow is self-hosted, which `dev/ci_contract.py` enforces
through `runner_placement`. Three workflows were reachable from `pull_request`:

- `.github/workflows/merge-gate.yml:33` guarded its `basic` job with the fork
  clause only, and its trigger list at line 9 omitted `labeled`, so no label could
  release a run. Its `gate` job ran under `if: always()` and failed any non-success
  `basic` result with one message, so a skipped job and a broken job read alike.
- `.github/workflows/migrations.yml:6` declared a bare `pull_request:` with no base
  filter and no guard at all on the `migrate` job, which checks out the pull
  request's tree and runs its migrations on the fleet.
- `.github/workflows/runner-policy.yml:3` declared a bare `push:` and a bare
  `pull_request:`. The bare `push` matters twice: it also matches tag refs. Its job
  at line 10 carried the fork clause only.

The fork clause does not reach the case that occurs. An automated dependency pull
request is opened on a branch of this repository, so `head.repo.full_name` equals
the repository, and its `author_association` is CONTRIBUTOR.

`.github/workflows/claude.yml` admitted `OWNER`, `MEMBER` and `COLLABORATOR` across
four event branches, first at line 23. This is a personal account, so `MEMBER`
names no one and is a widening with no corresponding population.

No guard test anywhere in `dev/` asserted a fork clause, an author association, or
a trigger set: a search across `dev/` for `author_association` and for
`full_name == github.repository` found matches only inside
`dev/tests/test_release_please_automation.py` and
`dev/tests/test_release_workflow_contract.py`, and in both cases only as pinned
text of the release workflows, not as a rule over every workflow.

### Where guards live and what runs them

`dev/tests/` holds the harness's workflow and release contract guards;
`dev/guards/` holds the format, exit-code and retired-invocation guards. Both are
collected by the `harness` test target, which is `pytest dev` under the
repository's process owner, declared in `dev/toolchain.py`. `just ci-merge` runs
that target, so a guard added under `dev/tests/` is on the pull-request critical
path. Tests there run under the runner at
`src/vaultspec_a2a/testing/runner.py`, invoked as
`python -m vaultspec_a2a.testing.runner -- <pytest args>`.

### The CI contract on shell steps

`dev/ci_contract.py` permits a workflow `run:` step to invoke only `just` or `gh`,
taking the first command line of a block scalar as the step's invocation, and
keys exemptions on the step's NAME in `.github/ci-contract-allow.txt`. A step
whose block opens with `set -euo pipefail` therefore needs an allowlist entry
regardless of what it goes on to call. The existing file already exempts
`merge-gate.yml:Judge the required checks` and
`release-please.yml:Refresh the release branch lockfile` under a
GitHub-state-bookkeeping reason, which is the same reason the cut's steps need.

### Release naming, as published

`gh release list` for this repository shows two releases, `v0.1.0` and `v0.2.0`,
titled `vaultspec-a2a v<version> — <summary>`. A recovery procedure that creates a
release by hand therefore titles it `vaultspec-a2a v<version>` to match the
published prefix.

### Maintainer documentation

There was no release documentation at all: a search of `docs/`, `README.md`,
`CONTRIBUTING.md` and `AGENTS.md` for release-please or releasing found nothing.
`docs/` is reStructuredText built by Sphinx, with `docs/development.rst` as the
contributor-facing guide and `docs/operations.rst` as the runtime guide, both
listed in `docs/index.rst`. `packaging/README.md:4` names `release.yml` as the
producer of the frozen onedir but states no trigger, so it needs no change.
