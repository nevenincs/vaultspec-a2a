---
tags:
  - '#plan'
  - '#provider-capability-evidence'
date: '2026-08-02'
modified: '2026-08-02'
body_hash: 'sha256:0594ba7497b7ec04803a012ba8ae369e6b614442b56951a18a8b1e1b884df02f'
tier: L2
related:
  - '[[2026-08-02-provider-capability-evidence-adr]]'
  - '[[2026-08-02-provider-capability-evidence-research]]'
---

# `provider-capability-evidence` plan

## Description

Execute the accepted execution-mode capability-evidence decision. The plan builds one immutable capability matrix from existing health, admission, web, and permission facts, then proves and discloses each provider lane without treating credential absence as unsupported or admission.

## Steps

### Phase `P01` - Capability contract and evidence derivation

Build the immutable execution-mode matrix and derive its facts from existing catalog, admission, web, and permission owners.

- [ ] `P01.S01` - Define immutable capability evidence, blockers, proof citations, and permission modes; `src/vaultspec_a2a/providers/provider_capabilities.py`.
- [ ] `P01.S02` - Derive complete exact-lane matrices from catalog health, admission, web proof, and permission policy; `src/vaultspec_a2a/providers/provider_capabilities.py`.

### Phase `P02` - Provider matrix proofs and served disclosure

Populate every external lane, prove available paths, preserve credential-blocked Kimi, and audit the resulting contract.

- [ ] `P02.S03` - Populate every registered external lane with support, blocker, and permission facts; `src/vaultspec_a2a/providers/factory.py`.
- [ ] `P02.S04` - Prove exact-lane capability disclosures and record review findings; `src/vaultspec_a2a/providers/tests/`.

## Parallelization

The matrix contract precedes provider population. Independent lane proofs may run in parallel only after the contract lands.

## Verification

Every external execution lane has a complete matrix record. Exact-lane proofs never transfer across modes. Capability claims activate only after their own real-behavior proof, and the final review records every finding.
