---
tags:
  - "#adr"
  - "#repository-tooling-hardening"
date: '2026-07-19'
related:
  - "[[2026-07-19-repository-tooling-hardening-research]]"
  - "[[2026-07-19-repository-tooling-hardening-reference]]"
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
  - '[[2026-07-15-dev-process-registry-adr]]'
supersedes:
  - '2026-03-19-control-layer-cli-justfile-separation-adr'
modified: '2026-07-19'
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
