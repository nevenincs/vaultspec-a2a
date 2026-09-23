---
tags:
  - '#plan'
  - '#project-bound-state'
date: '2026-09-23'
tier: L2
related:
  - '[[2026-09-23-project-bound-state-adr]]'
  - '[[2026-08-04-canonical-homes-adr]]'
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-15-dev-process-registry-adr]]'
modified: '2026-09-23'
body_schema: body-v2
body_hash: 'sha256:4e4c3681aa5b38905d7a9b1ccb88c012282a05dc421711153f116b962095336b'
---

# `project-bound-state` plan

## Description

Approved 2026-09-23. Basis: the user's in-session instruction to implement one
VAULTSPEC_A2A_ settings authority, project-bound default storage, relative-or-absolute
storage variables, worktree-contained test state and the dashboard patch, followed by
explicit answers to the four open forks and a direction to reconcile and fix everything
that surfaces.

`2026-09-23-project-bound-state-adr` governs every Step: D1-D3 bound Phase `P01`, D4
bounds Phase `P02`, D6 bounds Phase `P03`, D5 and the consequences bound Phase `P04`.
The measured surface is `2026-09-23-project-bound-state-reference`.
`2026-08-04-canonical-homes-adr` constrains every Step to one declaration with no shims.
The per-run execution root admission rules are out of scope and unchanged.

## Steps

### Phase `P01` - Settings authority

One settings module owns every a2a variable under VAULTSPEC_A2A_, resolves the project root, and replaces raw environment reads and literal child-environment names.

- [x] `P01.S01` - Resolve the project root by override, marker search, then working directory, split it from the install root, and read .env from it; `src/vaultspec_a2a/control/`.
- [x] `P01.S02` - Rename every a2a settings field to the VAULTSPEC_A2A_ prefix with foreign-tool fallbacks and one name registry for child environments; `src/vaultspec_a2a/`.
- [x] `P01.S03` - Enroll every raw environment read as a settings field and route consumers through settings; `src/vaultspec_a2a/`.
- [x] `P01.S04` - Regenerate .env.example from the settings fields and prove agreement with a contract test; `.env.example`.

### Phase `P02` - Project-bound storage

One layout derivation places all a2a state under the project-bound home and every writer resolves its location through it.

- [x] `P02.S05` - Derive one state layout for default and desktop homes, default the home to .vault/data/agents, and resolve relative storage paths against the project root; `src/vaultspec_a2a/control/`.
- [x] `P02.S06` - Route logs, discovery, singleton, process registry, worker-log sweep, provider temp homes and engine discovery through the layout; `src/vaultspec_a2a/`.
- [x] `P02.S07` - Align start, serve, setup and migrate on the single layout; `src/vaultspec_a2a/cli/`.

### Phase `P03` - Tests and tooling

Every test session, script and generator writes only inside an ignored worktree location with a unique per-session root.

- [x] `P03.S08` - Give every pytest session a unique worktree root holding basetemp, state home and process registry; `src/vaultspec_a2a/testing/`.
- [x] `P03.S09` - Remove test and tooling leaks into the profile and OS temp and close ignore gaps; `src/vaultspec_a2a/`.

### Phase `P04` - Deployment and cross-repo contract

Compose, container, process-registry configuration, documentation and the dashboard engine and launcher speak the new names and locations.

- [ ] `P04.S10` - Update compose files, container entrypoint, procs.toml and dev credential tooling to the new names and layout; `service/`.
- [ ] `P04.S11` - Patch the dashboard engine discovery, product launcher and agent E2E harness to the new names and location; `Y:/code/vaultspec-dashboard-worktrees/main/engine/`.
- [ ] `P04.S12` - Update operator documentation for configuration and storage; `README.md`.

## Parallelization

Phases run in order: each builds on the names and layout of the one before it. Within
`P04`, `P04.S11` (dashboard repository) can run beside `P04.S10` and `P04.S12` once
`P02` has landed, because its write set is a different repository.

## Verification

- No production module reads `os.environ` for an a2a variable outside the settings module,
  and no a2a variable outside `VAULTSPEC_A2A_` is accepted, proven by a source-scanning test.
- `.env.example` lists exactly the settings fields, proven by a contract test.
- A fresh process in a vaultspec project writes only under `<project>/.vault/data/agents`,
  verified by a live gateway boot with a sandboxed user profile.
- A full test run leaves the user profile's `.vaultspec-a2a` and `.vaultspec/procs` and the
  OS temp directory unchanged, verified by before-and-after listings.
- The dashboard engine discovers a project-bound gateway, proven by its own test suite.
- The plan-close review passes with every finding recorded in the feature audit.
