---
tags:
  - '#plan'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
tier: L3
related:
  - '[[2026-07-19-repository-tooling-hardening-adr]]'
  - '[[2026-07-19-repository-tooling-hardening-research]]'
  - '[[2026-07-19-repository-tooling-hardening-reference]]'
---

# `repository-tooling-hardening` plan

Deliver one locked, modular, clone-reproducible development and governance
control surface.

## Description

This plan executes `2026-07-19-repository-tooling-hardening-adr`, grounded by
the companion research and Core/RAG implementation reference. Wave W01 makes
the lock authoritative and provisions the framework tools. Wave W02 converges
governance and replaces dynamic command dispatch. Wave W03 makes validation
read-only and hardens hosted automation. Wave W04 publishes the contract and
closes the mandatory implementation-review-queue loop.

## Steps

## Wave `W01` - lock and provision the framework toolchain

Establish the project lock as the only Core and RAG execution authority before any generated surface changes.

### Phase `W01.P01` - dependency authority

Define explicit dependency profiles and make the lock authoritative for every Vaultspec tool invocation.

- [x] `W01.P01.S01` - Define explicit base, server, RAG, tooling, and all profiles with bounded Core and RAG upgrades; `pyproject.toml, uv.lock`.

### Phase `W01.P02` - framework lifecycle commands

Expose deterministic setup, upgrade, synchronization, and diagnosis without ambient-latest fallbacks.

- [x] `W01.P02.S02` - Add locked setup, sync, upgrade, status, and service recipes for Core and RAG; `just/dev/deps.just, just/dev/vault.just, just/dev/rag.just`.
- [x] `W01.P02.S03` - Route workspace provisioning and agent RAG acquisition through deliberate locked versions with real subprocess tests; `src/vaultspec_a2a/cli/provision.py, src/vaultspec_a2a/providers/_acp_mcp.py, tests`.

## Wave `W02` - reconcile governance and redesign the command facade

Land clone-persistent governance and then replace dynamic dispatch with owner-thin native modules.

### Phase `W02.P03` - Core-owned Git-ignore and rules

Converge effective Git policy and canonical rules through Vaultspec Core ownership.

- [x] `W02.P03.S04` - Remove obsolete broad framework ignores and prove Core-managed policy convergence; `.gitignore`.
- [ ] `W02.P03.S05` - Reconcile the compact custom rule corpus and regenerate provider projections through owning verbs; `.vaultspec/rules, generated provider projections`.

### Phase `W02.P04` - native Just modules

Replace the monolithic dispatcher with a discoverable portable module hierarchy.

- [ ] `W02.P04.S06` - Replace dynamic dispatch with a minimum-version-checked native module index and modular developer surface; `Justfile, just/dev`.
- [ ] `W02.P04.S07` - Route named services only through the process registry and stacks only through Compose; `just/dev/service.just, just/dev/stack.just`.

## Wave `W03` - unify validation and harden hosted automation

Make one read-only gate authoritative and consume it from hooks and GitHub.

### Phase `W03.P05` - local gates and debt

Separate validation from repair and reduce currently classified code-health debt.

- [ ] `W03.P05.S08` - Convert hooks to locked read-only validation with explicit repair and synchronization commands; `.pre-commit-config.yaml, hook integration tests`.
- [ ] `W03.P05.S09` - Remediate formatter, typing, dependency, and test-selection debt without suppressive shortcuts; `pyproject.toml, affected source and tests`.

### Phase `W03.P06` - hosted enforcement

Apply the local contract and least-privilege security boundary to hosted automation.

- [ ] `W03.P06.S10` - Invoke canonical CI, pin actions, minimize permissions, and authorize self-hosted dispatch before secrets; `.github/workflows, repository health configuration`.

## Wave `W04` - document, verify, review, and queue

Publish the executable contract, exercise it end to end, and close the mandated audit loop.

### Phase `W04.P07` - documentation pipeline

Ship separated onboarding, how-to, reference, and explanation surfaces that match executable commands.

- [ ] `W04.P07.S11` - Rewrite onboarding and add separated setup, command, operating-model, and vocabulary documentation through the documentation pipeline; `README.md, docs`.

### Phase `W04.P08` - acceptance and audit closure

Run real-behavior acceptance, review the implementation, and queue every finding.

- [ ] `W04.P08.S12` - Run clone-to-CI acceptance, formal review, finding classification, audit queue updates, and execution summaries; `.vault/audit, .vault/exec`.

## Parallelization

Waves execute in order. In W01, S01 precedes S02 and S03; S02 and S03 may then
run in parallel. In W02, S04 precedes S05; S06 may run alongside the governance
work, while S07 follows S06. In W03, S08 and S09 may begin together; S10 follows
the final local CI contract. Documentation context gathering may begin after
the public command surface freezes, but S11 lands after W03. S12 is terminal.

## Verification

- Every dependency profile resolves from `uv.lock`, and project-run Core and
  RAG versions match the declared constraints.
- Core install and sync converge twice without changing user-owned Git-ignore
  entries; canonical and provider paths are trackable while runtime state stays
  ignored.
- Rule status, full sync preview, spec doctor, plan check, and vault check pass
  without scope-introduced errors.
- `just` formatting, listing, nested help, and representative dry-runs pass on
  native PowerShell; no recipe directly spawns or force-kills a managed service.
- Hooks and CI are read-only, GitHub workflows validate, and self-hosted issue
  dispatch cannot reach secrets without trusted authorization.
- Ruff lint and format, Ty, classified Deptry checks, truthful test collection,
  all feasible real test suites, package build, Core doctor, and RAG status run
  with their outcomes recorded.
- Documentation command samples match executable help and pass technical,
  zero-context editorial, link, and Sphinx review.
- Formal code review classifies every finding and records each one in the audit
  queue before every Step and summary is closed.
