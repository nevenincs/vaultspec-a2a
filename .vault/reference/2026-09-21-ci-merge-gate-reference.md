---
tags:
  - '#reference'
  - '#ci-merge-gate'
date: '2026-09-21'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:0187ce847953fe816e299f864cddc1ec326954ff64873c2e763a337aa80cfbd5'
related:
  - "[[2026-07-19-repository-tooling-hardening-adr]]"
---

# `ci-merge-gate` reference: `Core and RAG merge-gate patterns`

Core commit `066eee7670c5de301b147825645bc3d60fff91f7` and RAG commit
`2cc134430703e0bccda1a713d554e98126416ca7` were inspected as the working
references requested by the repository owner.

## Summary

### One stable aggregate is the branch-protection contract

Core declares `Check: Merge gate (Linux)` as the sole required status and makes
the job depend on every measuring lane in `.github/workflows/merge-gate.yml:23`
and `.github/workflows/merge-gate.yml:257`. RAG applies the same name and
never-skipped aggregate in `.github/workflows/merge-gate.yml:12` and
`.github/workflows/merge-gate.yml:301`.

### Job names encode kind, subject, and platform

Core names blocking inspection jobs `Check: ...`, behavior suites `Test: ...`,
and includes the platform suffix at `.github/workflows/merge-gate.yml:71`,
`.github/workflows/merge-gate.yml:136`, and
`.github/workflows/merge-gate.yml:257`. RAG enforces the grammar in
`dev/guards/test_ci_job_names.py:5` and binds the required name in
`dev/guards/test_ci_lanes.py:32`.

### The aggregate must run and judge every trigger

RAG uses `if: always()` because a skipped required job can be treated as
passing at `.github/workflows/merge-gate.yml:297`. That is the stronger fit
here because cancellation must not create an ambiguous green signal.

### The local required lane should be Linux-only and declarative

The canonical pipeline is owned by `dev/toolchain.py:967` and exposed by
`justfile:977`; `.github/workflows/test.yml:122` already delegates to it. The
release-grade `ci all` also builds every distributable. A distinct declarative
merge target can retain dependency coherence, blocking lint, Vault validation,
harness guards, and resource-aware parallel pure-unit tests without moving
command logic into YAML. Desktop, provider, Compose, migration, release, and
advisory lanes remain visible but do not belong to the minimal required
aggregate.

### Local guards stop at the code ownership boundary

Core validates trigger behavior, exact job names, dependencies, and aggregate
semantics in `dev/guards/test_ci_check_shape.py:57` and
`dev/guards/test_ci_check_shape.py:364`. RAG validates naming and lane
aggregation in `dev/guards/test_ci_job_names.py:229` and
`dev/guards/test_ci_lanes.py:118`. Those repositories demonstrate the pattern,
but this project does not own fleet topology or runner registration. Its local
guard therefore binds only code-owned recipe composition and command routing;
it does not parse workflows to assert runner labels, runner platforms, or
hosted-versus-self-hosted placement.
### Release proposals and publication are separate fail-closed stages

Core commit `6c7e549a3b0a2087a78be1823a3bb9f13f49ff50` makes release-please the only version and changelog proposal owner. Its configuration creates draft releases at `release-please-config.json:7`; `.github/workflows/release-please.yml:149` explicitly dispatches the merge gate for the generated branch because default-token pull requests do not trigger it, and `.github/workflows/release-please.yml:172` dispatches the release workflow only after release creation.

The release workflow resolves current policy from the default branch while proving the immutable tag. `.github/workflows/release.yml:50` calls the reusable merge gate before publication, and `.github/workflows/merge-gate.yml:40,80` accepts and checks out the explicit ref. Core then sequences the irreversible publication behind the complete artifact build rather than reacting directly to a tag push.
### Core binary publication proves artifacts in stages and does not claim platform signing

Core commit `6c7e549a3b0a2087a78be1823a3bb9f13f49ff50` builds one tagged wheel and a native target matrix, but build output is named `unverified-*` and cannot be attached directly. `.github/workflows/binaries.yml:402-420` packages each bundle as unverified; `.github/workflows/binaries.yml:456-550` repeats the target matrix for an offline-start gate; `.github/workflows/binaries.yml:805-832` requires evidence that an isolation check ran before republishing the artifact as `binaries-*`.

Provenance is a distinct least-privilege job. `.github/workflows/binaries.yml:834-878` explicitly says GitHub/Sigstore attestation is not Authenticode, Apple code-signing, notarization, SmartScreen reputation, or a Gatekeeper trust grant. `.github/workflows/binaries.yml:894-1014` gives only `contents: read`, `id-token: write`, and `attestations: write` to a job with no source checkout, derives a non-empty immutable-archive subject set, and invokes a pinned `actions/attest` commit.

Attachment and publication are also separate. `.github/workflows/binaries.yml:1025-1066` refuses upload after failed attestation; `:1213-1248` proves the declared target cohort and attaches it; `:1274-1360` re-derives the attached set and verifies every archive against both the repository and the exact signer workflow. `:1376-1456` re-reads the draft release and refuses an incomplete set. Only the downstream publication workflow removes draft status after its own distribution checks. The mapped A2A flow therefore needs broad tag-bound validation, native lifecycle proof, isolated archive provenance, verification of the attached bytes, and publication last. It must describe the result as provenance rather than code-signing.
