---
tags:
  - "#adr"
  - "#repository-tooling-hardening"
date: '2026-07-19'
related:
  - '[[2026-07-19-repository-tooling-hardening-research]]'
  - '[[2026-07-19-repository-tooling-hardening-reference]]'
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
  - '[[2026-07-15-dev-process-registry-adr]]'
  - '[[2026-08-01-repository-tooling-hardening-strict-quality-gates-research]]'
  - '[[2026-08-01-repository-tooling-hardening-strict-quality-gates-reference]]'
  - '[[2026-10-06-codebase-remediation-audit]]'
  - '[[2026-08-04-canonical-homes-adr]]'
supersedes:
  - '2026-03-19-control-layer-cli-justfile-separation-adr'
modified: '2026-10-07'
body_hash: 'sha256:26770fb2d2719bd74048bb5e149f68a5ceb8aae593558c2dfd8a2c05b376c6fd'
---
# `repository-tooling-hardening` adr: `one modular, locked, and reproducible repository control surface` | (**status:** `accepted`)

## Problem Statement

The repository has incompatible owners for development process lifecycle,
validation, Vaultspec provisioning, generated governance, and hosted
automation. The superseded control-layer record and historical development
guidance prescribe direct foreground processes, while the accepted process
registry requires named lifecycle verbs. Tool
versions, Git-ignore policy, hooks, and CI also vary by entry point, so a working
environment cannot be reproduced reliably from the Git tree. We need one
repository control-surface decision that preserves product/tooling separation
while reconciling these ownership conflicts. Grounding:
`2026-07-19-repository-tooling-hardening-research` and
`2026-07-19-repository-tooling-hardening-reference`.

## Considerations

- Product behavior stays in `vaultspec-a2a`; `just` remains a discoverable
  developer and operator facade.
- The process registry exclusively owns named host-process lifecycle; Compose
  owns multi-service stacks.
- The agent-harness contract requires Core, RAG, rules, skills, templates, and
  provider surfaces to be provisioned and version-skew to fail visibly.
- Validation is read-only; synchronization, formatting, dependency upgrades,
  and repair require explicit commands.
- A fresh clone contains the team's canonical Vaultspec inputs and reproducible
  provider projections.
- Windows is a first-class host; recipes cannot depend on POSIX-only process or
  shell behavior.
- Repository automation does not hand untrusted issue content or credentials to
  persistent self-hosted infrastructure.

## Considered options

- **Patch the monolithic dispatcher and retain ambient tools and broad
  ignores.** Rejected: command discovery, versions, lifecycle ownership, and
  governance persistence remain independent contracts.
- **Move orchestration into the product CLI or a new Python supervisor.**
  Rejected: this crosses the product/tooling boundary and duplicates the process
  registry and Compose.
- **Use native `just` modules over project-locked tools, the registry, Compose,
  and explicit Core maintenance verbs.** Chosen: every responsibility keeps one
  executable owner while the repository exposes one discoverable interface.

## Constraints

- Setup and doctor checks fail with an actionable minimum `just` version.
- `2026-07-15-dev-process-registry-adr` remains a stable parent: no recipe
  independently spawns, finds, or kills a managed gateway, worker, or engine.
- `2026-07-15-agent-harness-provisioning-adr` remains a stable parent:
  provisioning does not widen agent-reachable write or MCP surfaces.
- `2026-03-20-service-lifecycle-architecture-adr` remains the accepted owner of
  Compose's product topology and stack lifecycle.
- `2026-07-15-dev-process-registry-adr` exclusively owns named host-process
  identity, port allocation, registration, and lifecycle verbs. This record
  owns only the repository command surface that delegates to those verbs.
- Core's marker-bounded Git-ignore writer is the only framework-ignore owner.
- Package upgrades are deliberate lockfile mutations followed by convergence
  checks; validation never installs an ambient latest version.
- Existing code-health debt is classified and reduced explicitly, never hidden
  with skipped checks, duplicated logic, or synthetic passing tests.

## Implementation

- Replace the root dispatcher with native `just` modules for code health,
  tests, services, stacks, builds, dependencies, hooks, Vaultspec maintenance,
  and product passthrough. Modules contain no product or lifecycle logic.
- Route named host processes through `vaultspec-a2a procs` and stacks through
  Compose. Remove substring process discovery, port-wide force-kill behavior,
  and direct managed-service spawning from recipes.
- Supersede the legacy control-layer `just` contract. Delegate named
  host-process lifecycle to the dev-process registry, which refines the
  service-lifecycle record's historical development boundary. This record does
  not supersede its Compose or product-lifecycle decisions.
- Define one read-only CI contract for local runs, hooks, and GitHub Actions.
  Separate repair commands own formatting, synchronization, indexing, and
  generated-file updates.
- Provide explicit base, server, RAG, tooling, and all dependency profiles.
  Execute Core and RAG from the project lock; provision and upgrade commands
  verify versions and convergence.
- Remove only obsolete external broad ignores, then let project-locked Core
  reconcile its managed block. Track canonical `.vaultspec`, provider
  projections, synthesized instructions, and repository agent guidance.
- Reconcile custom rules through Core's owning verbs, retaining a compact
  repository policy and removing obsolete persona/workflow duplicates.
- Harden hosted workflows with immutable action pins, least permissions, and a
  trusted-actor gate before issue-triggered self-hosted dispatch.
- Keep the README as an onboarding landing page, with focused how-to,
  reference, and explanation documents linked from it.

## Rationale

The knockout criterion is single ownership with clone-to-CI reproducibility.
`just` is the interface without becoming an implementation owner: the registry
owns host processes, Compose owns stacks, the lock owns tool versions, Core owns
framework Git-ignore and projections, and the shared CI contract owns
validation. Neither rejected option removes every conflicting ownership path;
the verified Core behavior also makes a second Git-ignore implementation
unnecessary.

## Consequences

- Gains: discoverable commands, intentional Core/RAG setup, one CI contract,
  owner-safe processes, clone-persistent governance, and Core-driven ignore
  upgrades.
- Costs: recipes, hooks, workflows, tracked projections, and documentation move
  together; existing formatter, typing, dependency, and test debt must be
  classified during adoption.
- Neutral: developers still need `just`, `uv`, and Docker for the surfaces they
  use, but setup verifies profile-specific prerequisites.
- Pitfalls: ambient CLIs, direct provider edits, framework entries outside the
  Core block, or direct process management recreate split ownership.
- Opens: a dedicated Core Git-ignore diagnostics verb, registry-managed RAG
  services, and stricter hosted controls when repository-plan capabilities
  permit them.

## Amendment (2026-08-01, no version pinning of independently released capabilities)

Reversal, on the owner's ruling. The Constraint "Package upgrades are deliberate
lockfile mutations followed by convergence checks" and the Implementation bullet
"Execute Core and RAG from the project lock; provision and upgrade commands
verify versions and convergence" were read, at
`repository-tooling-hardening-W01-P02-S03`, as licence to write an exact version
into a RUNTIME LAUNCH SPEC: the agent harness acquired its RAG MCP capability as
`uvx --from vaultspec-rag[mcp]==0.3.2 vaultspec-search-mcp`, with a recipe gate
failing the build whenever that literal drifted from the installed version. That
reading is now wrong, and the record is refined rather than superseded.

The ruling: a version constraint on a separately released capability is
forbidden here in every form - exact pin, floor, ceiling, or compatible-release
alike. Reproducibility was the stated gain; its cost is that this project's
upgrade cadence becomes a gate on every consumer of the wider ecosystem, and the
upgrade burden is pushed outward onto all of them. The owner has ruled that cost
too high against ecosystem development velocity.

The evidence agrees with the ruling on its own terms. By 2026-08-01 the pin had
gone stale against this very repository: the `rag` extra declared
`vaultspec-rag[mcp]>=0.3.8` while the launch spec still demanded `==0.3.2`, so
the convergence gate the pin existed to satisfy was itself red, and every
`setup`, `install`, and `upgrade` path through it failed. A pin its own project
has already outgrown buys no reproducibility - only breakage.

What replaces it: the CONTRACT, asserted rather than merely declared. The harness
registry already names, per server, the read-only tools a run expects it to
serve; those names become the autonomous allowlist and the Codex `enabled_tools`
set. That declaration is now load-bearing - verified against the server's own
`tools/list` over a real MCP handshake before a run launches, at the two seams
where a run commits to launching the declared set (the ACP spawn, beside the
existing isolation refusal, and the Codex home emission). A server that does not
serve a declared tool, or that cannot be probed at all, is refused with a message
naming the missing tool; an unverifiable contract is treated as an unmet one. The
compatibility boundary becomes the served tool surface - the thing a run actually
depends on - rather than a version number standing in for it. This converts a
declared-but-unchecked contract, the defect class this repository keeps
rediscovering, into a checked one, so the reversal strengthens the guarantee it
removes.

Scope, precisely. This amendment governs version constraints written into RUNTIME
ACQUISITION of capabilities released independently of this project. It does NOT
relax the record's other locking authority: `uv.lock` and `uv sync --locked`
remain the reproducibility mechanism for this project's own development
environment, and hosted workflows keep their immutable action pins. Those bind
only this repository's own builds; they never constrain a consumer's resolution,
which is the harm being ruled out.

Upstream, `vaultspec-core#300` and `vaultspec-rag#337` ask both servers for a
`--read-only` launch mode on the same principle - consumers assert the served
surface rather than pin a version. The launch specs are shaped so that adopting
the flag is a one-line addition to `args`, not a rework.
## Amendment (2026-08-01, staged strict-quality enforcement)

The canonical validation contract is refined to distinguish three states for every quality dimension: visible advisory, blocking gate, and reviewed investigation lead. This refines the existing read-only CI contract, rather than creating an owner or superseding decision. Grounding: `2026-08-01-repository-tooling-hardening-strict-quality-gates-research` and `2026-08-01-repository-tooling-hardening-strict-quality-gates-reference`.

`dev/toolchain.py` remains the sole owner of target names, commands, scan scope, composition, and failure behavior. `pyproject.toml` owns tool configuration and thresholds. The root `justfile` remains a facade that delegates canonical CI to the declarative harness. Hosted workflows own scheduling, platforms, and result presentation only: they invoke named harness targets and never restate commands, paths, exclusions, or thresholds.

The deterministic sentinels are `type-strict`, `type-platforms`, `complexity`, `cyclomatic`, `shape`, `limits`, `nesting`, and `size`. Every one runs in its own hosted-CI step on every push and pull request, guarded by `if: ${{ !cancelled() }}`. A sentinel with standing debt remains locally strict but has a visible hosted result with `continue-on-error: true`. A graduated sentinel is simultaneously a member of `lint all` and a blocking hosted step; `lint strict` stays the local keep-going dashboard rather than the hosted result boundary.

Promotion is atomic and evidence-bound. A deterministic sentinel may graduate only after its existing threshold and scope produce zero findings without new exclusions, suppressions, baselines, threshold increases, or duplicated code; that result is reproduced from the lock in a clean settled checkout at the candidate commit; canonical `just ci` passes there; affected integration, service, desktop, or acceptance obligations are green or precisely out of scope; and the one promotion change adds the target to `lint all` while removing its hosted `continue-on-error`. After graduation, a regression is repaired rather than hidden through demotion, scope narrowing, or threshold changes; any reversal requires a new grounded amendment.

A2A adds `type-platforms` as a first-class Ty target over the committed Python roots under Python 3.13 for `linux`, `darwin`, and `win32`. It starts as advisory evidence and shares the same promotion invariant. A2A does not copy a Core or RAG exception without a local census and demonstrated white-box ownership need.

Duplication remains a reviewed investigation lead. `audit duplication` continues production-only JSCPD scanning at 20 lines and 70 tokens, gains a named advisory hosted step, and never joins `lint all` solely because one run is zero. Any later blocking clone policy needs a separate decision defining adjudication, legitimate-copy categories, generated/migration treatment, exclusion ownership, and false-positive disposition.

Static quality does not certify runtime behavior. Unit, service, desktop, Compose, provider-live, cross-repository, and acceptance lanes retain their distinct prerequisites. The static-quality job starts no service, uses no provider credential, dispatches no GPU work, and does not infer runtime certification from a type or complexity verdict.

A real-code anti-drift guard is mandatory. It imports the declarative registry and inspects the tracked root `justfile` and hosted workflow without mocks, patches, or mirrored command logic. The guard proves root `just ci` delegates to the sole declarative CI owner; the hosted job invokes `just ci`; every strict sentinel has exactly one visible hosted step; blocking membership exactly matches `lint all`; advisory sentinels carry `continue-on-error`; hosted steps invoke named targets only; duplication remains advisory and outside `lint all`; and `type-platforms` covers exactly the three declared platforms over the canonical Python paths.

## Amendment (2026-08-01, canonical anti-drift enforcement)

The anti-drift guard is a required canonical CI check, not a workflow-only diagnostic. `CI.all` runs `test harness` after Vault validation and before `test unit`. The `TEST.harness` target retains exclusive ownership of `pytest dev`; the hosted workflow adds no separate harness step and product `testpaths` remain unchanged. Root `just ci` and the hosted workflow's existing `just ci` invocation therefore enforce the same guard through the sole declarative CI owner.

## Amendment (2026-10-07): blocking duplication enforcement, one owner per quality dimension, and no R0902

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

This amendment is the separate decision that the staged strict-quality amendment requires before any blocking clone policy. It refines that amendment and does not supersede this record. Grounding: findings R6-F18, R6-F32, R7-F13, R3-F19 and R4-F24 in `2026-10-06-codebase-remediation-audit`.

**Duplication enforcement is blocking.** Two detectors own two distinct clone dimensions, and both block.

- *Structural clones* are function bodies that are identical once every identifier is erased. The AST guard `src/vaultspec_a2a/tests/test_structural_duplication.py` owns them. It runs in `test unit`, which canonical CI runs. Its roots widen from the package alone (`:46`) to `src`, `dev`, `packaging`, `scripts` and the repository-root `conftest.py`. Tiers come from the canonical tier list in `dev/paths.py` plus `testing`, replacing the path heuristic at `:213-216`. A cross-tier pass compares test functions against production functions; today groups are compared within one tier only (`:219-235`). Each root asserts a visited-files floor. An unparseable file fails the guard instead of being skipped (`:228`). An accepted group needs a written reason. A group that exists only to satisfy a lint threshold is not accepted.
- *Copy-paste spans* are owned by JSCPD through `audit duplication` (`dev/audit/duplication.py`). JSCPD is pinned as a development dependency in `package.json` and locked in `package-lock.json`. The floating `npx` spec `jscpd@4` (`dev/audit/duplication.py:60`) is retired. The scan widens from production only (`:63`, `:72`) to every test tier, `testing`, `dev`, `packaging` and `scripts`. The 20-line, 70-token threshold is unchanged. The scan blocks against an adjudicated baseline: the target joins `lint all`, and its hosted step loses `continue-on-error` (`.github/workflows/test.yml:137-140`).

The baseline may not grow. A new clone is removed, never baselined. An entry leaves when its clone is removed, and a stale entry fails the gate, so the baseline only shrinks. Adjudication follows these rules:

- *Legitimate-copy categories.* `distinct-semantics` covers one shape applied to a different table, column, event kind or schema. `oracle` covers a test's independent derivation of an external contract, kept so the test does not import the logic it checks. Each entry carries exactly one category and a written reason.
- *Debt.* An entry in neither category is debt. It names the Step that removes it, and no debt entry survives the close of `2026-10-06-codebase-remediation-plan`.
- *Generated and migration files.* Generated output and Alembic revision scripts are excluded by path, not baselined. Migration history is immutable, and generated text has one source.
- *Exclusion ownership.* `dev/audit/duplication.py` owns the duplication scan scope, thresholds and path exclusions. The baseline file owns the adjudicated entries. `dev/toolchain.py` keeps the target name, composition and failure behaviour. Nothing else restates them.
- *False positives.* A reported span that is not a copy is adjudicated as `distinct-semantics` with its reason. Thresholds and scope never change to hide a report.

The duplication baseline is the only baseline gate. The promotion invariant for the deterministic sentinels still forbids baselines. The gate complements the rehoming rule of `2026-08-04-canonical-homes-adr` and does not replace it. That record rejected a lint that freezes existing copies; here debt entries are removed, not kept.

**One owner per quality dimension.** Each dimension has exactly one gate:

- cyclomatic complexity: ruff `C901` in `limits` (`dev/toolchain.py:118`, ceiling in `[tool.ruff.lint.mccabe]`);
- function returns, branches, arguments and statements: ruff `PLR0911`, `PLR0912`, `PLR0913` and `PLR0915` in `limits`;
- nesting depth: ruff `PLR1702` in `nesting`;
- module length, public methods and boolean expressions: pylint `C0302`, `R0904` and `R0916` in `size`;
- cognitive complexity: complexipy in `complexity`;
- structural clones and copy-paste spans: the two duplication detectors above.

`dev.health` gates no dimension. It stays a ranking report that always exits 0. The `cyclomatic` target (`dev/toolchain.py:405-409`, `health --gate cyclomatic`) is retired. It duplicates ruff `C901`, as `dev/health/report.py:384-395` itself records. The `shape` target (`dev/toolchain.py:410-414`, `health --gate`) is retired by the same rule. It re-measures module lines, statements, arguments and nesting at the thresholds that pylint `C0302` and ruff `PLR0915`, `PLR0913` and `PLR1702` already gate (`dev/health/report.py:79-82` against `pyproject.toml:373,376,552` and `dev/toolchain.py:422`). The false-pass exit of `health --gate` (`dev/health/__main__.py:67-72`) goes with the gate.

**R0902 is disabled for the project.** pylint `too-many-instance-attributes` leaves the enabled set, and `max-attributes` is dropped (`pyproject.toml:545,555`). Record size is not a complexity signal. The rule produced four field-binder machineries and eleven inline suppressions across six modules (R7-F13, R3-F19, R4-F24). Those binders and suppressions are removed, not relocated. Records are plain keyword-only frozen dataclasses grouped by meaning. Complexity stays owned by the gates above.

**Replaced clauses.** In the staged strict-quality amendment:

- The deterministic sentinel list loses `cyclomatic` and `shape`. It is now `type-strict`, `type-platforms`, `complexity`, `limits`, `nesting` and `size`.
- This amendment replaces the paragraph that begins "Duplication remains a reviewed investigation lead" and ends "false-positive disposition".
- In the anti-drift guard, "duplication remains advisory and outside `lint all`" becomes: the duplication target is a blocking member of `lint all`, with one visible hosted step and no `continue-on-error`.
- "`dev/toolchain.py` remains the sole owner of target names, commands, scan scope, composition, and failure behavior" now excepts the duplication scan scope, which `dev/audit/duplication.py` owns.

The 2026-08-01 rule against version constraints on independently released capabilities does not apply to JSCPD. JSCPD is this repository's own development tool, and its lock binds only this repository's builds.

Reconsider the baseline rule if a legitimate copy fits neither category. Reconsider the R0902 ruling if record width is shown to cause defects that the remaining gates miss.
