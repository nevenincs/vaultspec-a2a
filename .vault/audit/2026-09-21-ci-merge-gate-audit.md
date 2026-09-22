---
tags:
  - '#audit'
  - '#ci-merge-gate'
date: '2026-09-21'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:912e9c90fd16caeba1d375c62148c29c5790539f55d9009547bb7ec47a2d45de'
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

### runner-topology-ownership | medium | fleet and CI-runner tests removed from the project

Type: ownership boundary. Status: fixed and verified. The repository owner
ruled that fleet registration, runner labels, and hosted-versus-self-hosted
placement are infrastructure concerns outside this coding project's scope.
`dev/tests/test_ci_contract.py` no longer parses `merge-gate.yml` or asserts
`runs-on` values, exact runner platforms, or job placement. The custom
`.github/actionlint.yaml` runner-label registry is deleted. Workflow syntax and
the code-owned declarative recipe contract remain tested without claiming
authority over infrastructure.

### runner-ownership-rereview | low | PASS with no critical or high findings

Type: focused implementation review. Status: verified. The cleanup deletes the
only test that parsed CI runner placement, removes the repository's custom
runner-label registry, and disables only actionlint's unknown-runner-label
diagnostic. Workflow parsing, action pin validation, recipe delegation, and the
declarative merge profile remain enforced. A repository-wide search of test
modules finds no runner selector, availability, registration, or topology
assertion.

## Recommendations

- Reclassify or restructure the provider factory test so the `unit` marker no
  longer depends on an installed Node package, then measure whether the merge
  job can safely return to `just init`.
- Publish the two implementation commits before expecting existing pull
  requests to become mergeable; do not weaken or remove the required context
  during that interval.
- Keep future CI tests limited to repository-owned commands and behavior. Do
  not add runner availability, label registration, fleet topology, or runner
  placement assertions back to this codebase.
### release-pipeline-ownership | high | fixed and verified

Type: release integrity and workflow authorization. Status: fixed. The prior workflow combined manual metadata preparation with tag-push publication and did not use release-please, so version proposals, review, immutable-tag proof, and publication were not sequenced like the Core reference. `release-please-config.json`, `.release-please-manifest.json`, `.github/workflows/release-please.yml`, the reusable merge gate, and the release workflow now implement the Core boundary: reviewed release PR, draft release, explicit tag gate, complete four-target cohort, asset upload, then publication. Focused contract tests and `just check-workflow` pass.

### mutable-claude-action-reference | high | fixed and verified

Type: supply-chain security. Status: fixed. Both Claude workflows used `anthropics/claude-code-action@main` despite the earlier audit recording an immutable pin. They now use observed commit `cfc3eb22bfed5c26ef66e3223c982af27e4524de`; actionlint and the workflow contract pass.

### current-certification-test-failures | high | open

Type: runtime correctness and CI blocking. Status: queued for remediation. GitHub run `35687795898` reached `just ci` and reported 4 failures among 4,615 passes: lazy-worker concurrent demand returned one HTTP 500, gateway readiness exhausted its one-port test band, the privileged symlink-swap confinement test raised `KeyError: result`, and the runner-child production fail-closed subprocess assertion failed. These are actual test failures, not workflow scheduling or permissions failures; the merge and certification workflows must continue reporting them. The confinement failure overlaps open-issue-remediation `P01.S10/P01.S11`; the remaining failures need ownership in the appropriate remediation Steps before closure.

### claude-review-opaque-runtime-error | medium | open

Type: external action runtime and diagnostics. Status: queued for follow-up. GitHub run `35687441681` completed checkout, OIDC exchange, GitHub App token acquisition, and actor authorization, then Claude Code returned `subtype: success` with `is_error: true`, zero cost, and no actionable provider error. The workflow must remain non-required until a real review completes reliably. Do not broaden its tools or token permissions without evidence naming a denied capability.

### release-flow-rereview | low | PASS with no unresolved critical findings

Type: integrated implementation review. Status: verified. The release proposal, merge proof, tag proof, native matrix, cohort validation, scoped upload, and final draft publication form one fail-closed chain. The release job grants write access only to the publishing job; checkout credentials remain disabled in build and validation jobs; action references are immutable; and the guard reads the actual workflow and configuration artifacts.
### automatic-llm-review | medium | removed

Type: review governance. Status: fixed by owner direction. The automatic Claude pull-request review workflow was superfluous to the professional merge contract and its opaque `is_error:true` result could not establish code quality. `.github/workflows/claude-code-review.yml` is removed. The interactive trusted-actor Claude workflow remains separate and is not a required review or merge signal.

### release-fast-gate-overclaim | high | fixed and verified

Type: release qualification. Status: fixed. A2A's `merge-gate.yml` intentionally runs a fast Linux subset, unlike Core's full Linux-and-Windows merge gate. Calling it “release health” overstated the evidence. `test.yml` is now `Full Validation`, accepts an explicit reusable ref, and every checkout binds to that ref. Release qualification calls this broad workflow against the immutable tag, so canonical CI, desktop service, provider prerequisites, Compose regression, documentation, and workflow contract all gate artifact construction.

### provenance-is-not-platform-signing | high | fixed and verified

Type: release security claim. Status: fixed. The release now follows Core's non-signing verification boundary: an isolated GitHub-hosted job receives only read, OIDC, and attestation grants; it attests exactly four immutable archives with pinned `actions/attest`; the upload job has only contents write; attached archives are downloaded again and verified against this repository and `.github/workflows/release.yml`; only then is the draft published. Comments and tests explicitly avoid claims of Authenticode, Apple signing, notarization, SmartScreen, or Gatekeeper trust.

### binary-release-rereview | low | PASS with no critical or high findings

Type: integrated workflow review. Status: verified. The stable chain is full tag-bound validation, native build and lifecycle execution, complete-cohort and checksum verification, isolated provenance, scoped attachment, verification of the attached bytes, and publication last. Actionlint, the repository workflow contract, focused formatting and type checks, and five real-artifact tests pass. Remaining release scripts listed in `.github/ci-contract-allow.txt` are visible migration debt rather than hidden workflow commands.
