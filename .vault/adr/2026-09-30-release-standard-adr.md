---
tags:
  - '#adr'
  - '#release-standard'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:e702afaf3e739ade4f23fa828530cec43e2ff1c9631f7b1269807d7abdb6c57d'
related:
  - '[[2026-09-30-release-standard-reference]]'
---

# `release-standard` adr: `Adopt the vaultspec release standard` | (**status:** `accepted`)

## Problem Statement

This repository released on every push to main and built its artifacts on every
tag push. Two consequences followed. A release happened whenever a release
commit landed, whether or not anyone wanted one, and the commit it released had
only ever been proved on its pull request head, not on the tree that landed.
Publication started twice for one tag whenever the tag push and a dispatch
coincided, because the lane listened for both.

A second problem sat beside it. Every runner here is self-hosted, and the
pull-request workflows started jobs for any author who could open a pull request
against a branch of this repository. The fork condition several jobs carried does
not reach them: an automated dependency pull request is opened on a branch of
this repository, with an author association of CONTRIBUTOR, and ran the fleet
unreviewed.

The maintainer authorized adopting one release standard across the vaultspec
repositories on 2026-09-30. vaultspec-core leads the standard; its record is
`2026-09-30-release-standard-adr` in that repository's vault. This record adopts
it here and states what adoption means for this repository's lanes.

## Considerations

- A release tag cannot be deleted, so a release commit proved after it is tagged
  leaves a permanent tag of a commit nobody can ship.
- The default workflow token never holds the `workflows` permission. Without it
  GitHub refuses any tag or release that targets a commit whose
  `.github/workflows` differ from the branch head, verified by probe. The tag
  must therefore follow the merge within seconds.
- No credential holding the `workflows` permission may exist in this repository,
  so the constraint above cannot be bought off with a token.
- This account's product is the frozen onedir, and the consuming composition
  keys on archive names derived from the tag. A release that is visible before
  its archives are attached is a release a consumer can read and fail on.
- An author association is the only trust signal available on a pull request that
  is not from a fork. Applying a label takes triage rights, so a label by a user
  is a second signal; a label by a bot is not.
- A required status check whose job is skipped counts as passed.

## Considered options

- **Adopt the standard as vaultspec-core implements it.** Chosen. One shape
  across repositories, so an operator reads the same checks list and the same
  recovery procedure everywhere, and a defect found in one repository is fixed in
  all of them.
- **Keep releasing on push and add a proof after the tag.** Rejected. It cannot
  work: the tag is already immutable when the proof fails.
- **Grant a credential with the `workflows` permission.** Rejected. It removes
  the tag constraint by giving continuous integration the ability to rewrite its
  own gates, which is a larger loss than the constraint costs.
- **Guard the fleet with the fork condition alone.** Rejected. It admits every
  non-fork author, which is the case that actually occurs here.
- **Require a label for every pull request.** Rejected. A tier only a label can
  reach is invisible in the checks list, and a maintainer's own change would
  stall behind a ritual.

## Constraints

- Tags here are bare `v<version>`: the configuration sets
  `include-component-in-tag` false, so the recovery runbook and the cut's own
  diagnosis must both derive `v${version}` and not a component-prefixed form.
- The release lane freezes natively per target and cannot cross-compile, so its
  target matrix is fixed by the runners available and the lane must resolve the
  workflow from main while checking out the tag for source.
- `release-please` opens no new proposal while one is pending, so the pending
  proposal is the only release candidate that can exist.
- The pull-request workflows must see the `labeled` event for the label clause to
  mean anything, and the required check must then still reach a verdict on a
  label that started nothing.

## Implementation

The proposal and the release are separated. A push to main refreshes the release
pull request only; `always-update` rebuilds its branch on main's newest head, and
the action runs with `skip-github-release`, so this path creates no tag, no
release and no publication. Merging the proposal by hand releases nothing either.

A maintainer dispatches the cut. It resolves the pending proposal and refuses a
candidate that is behind main or ambiguous, calls the full merge gate on that
candidate's exact head, squash-merges only that head with `--match-head-commit`,
and refuses the result if the landed tree is not the proven one. `release-please`
then forces the tag and creates an unpublished draft, and a following step
refuses a tag that points anywhere but the proven commit. A failure to tag is
diagnosed by name, because the API error names neither the tag nor its cause. The
cut ends by dispatching the release lane with the tag.

The release lane is dispatch-only. Nothing triggers on a tag push or a release
event, and every push trigger names its branches, because an unfiltered push
matches tag refs too. The lane attaches every archive and checksum to the draft,
attests and verifies provenance, and publishes the draft as its last step.

Every pull-request-reachable job on the fleet carries one condition: the author
is the owner or a collaborator, or a user has applied `ci:full`. The required
gate job is the single exception, because it must never be skipped; it refuses an
untrusted author's commit by name inside its own script, after looking for its
own earlier success on the same commit so that a label which started nothing does
not redden a proved commit. The agent workflow's author allowlist drops MEMBER:
this is a personal account, so there are no organisation members for it to admit.

Guard tests hold the shape: the cut is the only release authority, the cut waits
on the gate for the exact head, no workflow starts from a tag push or a release
event, the release is created as a draft with its tag forced, and the trust rule
covers every pull-request-reachable job in every workflow.

## Rationale

The ordering is forced rather than chosen. The proof must precede the tag because
the tag is immutable; the tag must follow the merge because the token cannot tag
across a workflow change; the publication must follow the archives because a
visible release is one a consumer will act on. Every alternative ordering loses
to one of those three, which is why the same shape holds in every repository that
adopts this standard.

The trust rule is written as plain equality on the author association rather than
through a membership function so that one string is shared across repositories
and an expression evaluator can decide it. The label clause exists because the
author clause has to refuse a contributor whose change is nevertheless worth
running, and the refusal has to name what releases it.

## Consequences

Releases now happen when asked for, and only on a tree that passed the gate it
landed as. The cost is a dispatch: a release commit that lands no longer becomes
a release on its own, and a maintainer who forgets to dispatch ships nothing.

A release can still become unfinishable, when a workflow change lands between a
release commit's merge and its tag. That case is now diagnosed by tag rather than
by an opaque API error, and the credentialed recovery is documented, but it
remains manual.

Automated dependency pull requests no longer run anything until a collaborator
reads them and applies `ci:full`. That is the intended cost. The gate refuses
such a commit by name, so the reason a branch is red is legible rather than
looking like a broken check.

The label is visible in the checks list only as an absence, so a contributor whose
pull request runs nothing depends on the gate's message to learn why. That message
is therefore load-bearing and is asserted by a guard test.
