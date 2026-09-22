---
tags:
  - '#audit'
  - '#issue-26-release-automation'
date: '2026-09-22'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:baf2169df37e71500862d285bbf5559ad7aa8e5f0761b58790a6fb4baa8dbcd9'
related:
  - "[[2026-09-22-issue-26-release-automation-plan]]"
---

# `issue-26-release-automation` audit: `release-please proposal lane`

## Scope

Reviewed the planned release-please config, manifest, workflow, and focused
contract test against the accepted Dashboard-subordination ADR, the retained
A2A artifact workflow, the A2A main ruleset, and the pinned vaultspec-core
reference. The review excludes actually creating a tag, GitHub release, or
artifact publication.

## Findings

### bot-pr-approval | medium | the first release proposal awaits administrator approval before its required check can run

Type: operational prerequisite. Status: open external acceptance blocker. GitHub
documents that `GITHUB_TOKEN`-created pull-request events run in an
approval-required state. The retained `.github/workflows/merge-gate.yml`
handles those pull-request events and reports the exact
`Check: Merge gate (Linux)` ruleset context after approval. A manual workflow
dispatch cannot satisfy that PR-required context, and switching to a PAT or
App token would make the later tag start `.github/workflows/release.yml`, which
would violate the retained artifact-publication guard. This is not a code
defect: an administrator must approve the bot-created release-PR run in the
first live exercise.

### implementation-self-review | low | no in-scope automation defect found before independent review

Type: implementation and integration. Status: provisional PASS. The workflow
is main-only, serialized, pinned, and uses no explicit token input. Its config
matches the root Python package and manifest, creates a draft release with a
forced `v` tag, and retains pre-1.0 conventional-commit behavior. It contains
no `gh workflow run` call, and it does not edit or dispatch the exact-tag,
four-target `.github/workflows/release.yml` publisher. Focused checks pass, but
an independent review is required before the Step closes.

## Recommendations

- Before treating the first release as successful, have a repository
  administrator approve the bot-created release PR workflow and verify the
  required check appears on that PR head.
- After Dashboard selects a candidate release set, use the existing guarded
  publication process; do not add a release-please dispatch to bypass it.
### publisher-chain-authority | high | automatic publication bypassed Dashboard release-set selection | resolved

The first cross-history merge temporarily retained a release-please step that dispatched the A2A publisher as soon as release-please created a tag. That contradicted the accepted Dashboard-subordination decision and the approved S01 boundary. The final workflow contains no `gh workflow run` command, has no `actions: write` permission, and leaves guarded artifact publication to the existing tag or explicit-tag publisher after Dashboard selection.

### publication-safeguard-preservation | high | initial issue snapshot omitted qualification and provenance gates | resolved

The unfinished issue-26 snapshot was based on the remote branch before local release hardening and therefore expressed publication as build then upload. Reconciliation retained the reusable full-validation health job, per-archive checksum verification, repository provenance attestation, attached-provenance verification, exact cohort enforcement, and publish-last transition. Release-please changes proposal ownership only; they do not weaken the artifact publisher.

### tag-filter-glob-semantics | medium | regex-style tag filter could not match normal release tags | resolved

The snapshot used regex quantifiers in a GitHub glob field. The final trigger uses broad `v*.*.*` matching, while the build's existing strict regular-expression and exact-ref checks remain the authority that rejects malformed or spoofed tags before construction.

### integrated-release-automation-review | low | approved S01 preserves the supplier-consumer authority boundary | PASS

Review traced proposal creation, version/manifest/lockfile ownership, historical changelog bootstrapping, pull-request gate behavior, immutable tag/ref qualification, native builds, checksums, provenance, cohort upload, and draft publication. Focused contract tests and the repository hook suite pass. The two high and one medium integration findings above are resolved. The existing administrator-approval prerequisite remains an explicitly owned operational item; no critical, high, or unowned medium implementation finding remains.
