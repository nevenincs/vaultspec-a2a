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
supersedes:
  - '2026-03-19-control-layer-cli-justfile-separation-adr'
modified: '2026-08-01'
body_hash: 'sha256:012049c81c40336904fc584d43fb254aed861f24251dd74e0b09ea3830508d63'
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
