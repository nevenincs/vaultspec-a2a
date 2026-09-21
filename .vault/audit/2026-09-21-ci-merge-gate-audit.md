---
tags:
  - '#audit'
  - '#ci-merge-gate'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:4d3cdab85bd7020ead5b1c6e95536501c06d043266541ef8948d6148aaafb1ee'
related:
  - "[[2026-09-21-ci-merge-gate-plan]]"
---

# `ci-merge-gate` audit: `integrated implementation review`

## Scope

Reviewed commits `e8064b28` and `31baa996` against the approved plan, the
accepted repository-tooling decision, and the Core and RAG reference pattern.
The review traced the root recipe through the declarative registry, workflow
measuring job, terminal aggregate, post-merge certification triggers,
real-artifact guard, and active GitHub ruleset.

## Findings

### integrated-contract | low | PASS with no critical or high findings

Type: correctness and policy enforcement. Status: verified. The exact
`Check: Merge gate (Linux)` name is shared by the committed workflow, the
real-artifact guard, and active `protect-main` ruleset 14280506. The terminal
job uses `always()`, depends on the only required measuring job, and fails every
non-success result. Fork code never reaches the self-hosted runner and therefore
cannot produce a green aggregate. Full certification no longer runs on pull
requests but remains scheduled on every push to `main` and manual dispatch.

### unit-marker-node-dependency | medium | one pure-unit test requires the real Node package tree

Type: test taxonomy and setup cost. Status: open. The first exact merge run
collected 1,952 `unit` cases and failed only
`src/vaultspec_a2a/providers/tests/test_factory.py:455` because that test
resolves the installed Claude ACP entry point. Installing the locked npm tree
made the same profile pass all 1,952 tests in 20.20 seconds. The hosted job must
therefore retain pinned Node setup and `just init-full`; the marker does not yet
support a Python-only worktree despite its pure-unit contract.

### unpublished-required-context | low | branch protection is ahead of the local workflow commits

Type: deployment sequencing. Status: open until publication. Ruleset 14280506
now requires `Check: Merge gate (Linux)` with strict up-to-date enforcement,
but commits `e8064b28` and `31baa996` remain local because no push was
authorized. This fails closed: pull requests cannot merge until these commits
are published and the new workflow reports its first verdict.

## Recommendations

- Reclassify or restructure the provider factory test so the `unit` marker no
  longer depends on an installed Node package, then measure whether the merge
  job can safely return to `just init`.
- Publish the two implementation commits before expecting existing pull
  requests to become mergeable; do not weaken or remove the required context
  during that interval.
