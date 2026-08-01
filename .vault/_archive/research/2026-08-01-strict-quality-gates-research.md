---
tags:
  - '#research'
  - '#strict-quality-gates'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:d5472836ae6072d8d0a2d545ea702e7c725ec9b10eda91a2798ac1ff74902753'
related:
  - "[[2026-07-19-repository-tooling-hardening-research]]"
  - "[[2026-07-19-codebase-health-research]]"
---
# `strict-quality-gates` research: `staged promotion of strict static gates`

The repository already exposes strict static-analysis and clone-detection commands, but its canonical CI intentionally runs only the dimensions with a current zero-debt ratchet. Core and RAG demonstrate two compatible promotion patterns: independent visibility for every dimension, and blocking enforcement only after fresh, settled-tree evidence supports it. The pending ADR must decide the A2A promotion protocol and its CI expression; it must not claim that static checks certify service behavior.

## Findings

### The existing A2A boundary separates verdicts from leads

A2A already treats Ruff, Ty, relative-import checks, dependency declarations, TOML, and workflow lint as blocking through `dev/toolchain.py:280-378`. Basedpyright strict, cognitive complexity, cyclomatic complexity, function shape, nesting, and module design are executable strict targets but intentionally remain outside `lint all` while their burndowns are nonzero (`dev/toolchain.py:260-399`). Current direct execution confirms that immediate promotion is not supportable: cyclomatic reports 104 violations and structural shape reports 5 module-length, 10 function-length, 76 parameter-count, and 9 nesting violations; strict typing also reports substantial diagnostics. This is a current-worktree measurement, not a settled-tree release claim.

Bandit, Vulture, JSCPD, docstring coverage, and test-tree complexity are advisory because their outputs require review before they can be treated as defects (`dev/toolchain.py:456-541`). Clone detection runs over production code at 20 lines and 70 tokens, matching the RAG detector configuration; it should remain a reviewed finding until an owner defines adjudication and false-positive policy.

### Core and RAG validate the same ownership model but differ by evidence maturity

Core keeps `justfile` thin over a declarative `dev/toolchain.py`, runs strict typing, cognitive complexity, nesting, and size independently in CI, and blocks on them only after their ratchets are green (`Y:/code/vaultspec-core-worktrees/main/dev/toolchain.py:194`, `Y:/code/vaultspec-core-worktrees/main/.github/workflows/ci.yml:116`). RAG exposes equivalent named targets, blocks strict typing after its burndown reached zero, and leaves complexity, nesting, and size visible but advisory in its comprehensive lane (`Y:/code/vaultspec-rag-worktrees/main/justfile:113`, `Y:/code/vaultspec-rag-worktrees/main/.github/workflows/ci.yml:78`).

The shared principle is therefore not an identical command list: command ownership is declarative, every sentinel is visible, and a sentinel becomes blocking only when the current repository can hold its configured threshold. Core's cross-platform Ty lane is relevant to A2A because A2A ships desktop behavior on Windows as well as Linux; RAG's GPU and self-hosted lane machinery is not reusable because it solves scarce-hardware and service-lifecycle constraints A2A static analysis does not have.

### CI aggregation is a contract and not service certification

`just ci` runs `lint all`, dependency audit, and the unit tier (`justfile:63-68`), and the hosted workflow invokes it (`.github/workflows/test.yml:42-46`). Changing `lint all` therefore changes the local and hosted required contract together. Static promotion must be independent of service evidence: unit execution excludes auto-marked service tests (`dev/toolchain.py:544-625`), while real-process service and cross-repository evidence have separately declared prerequisites.

A staged policy needs four proofs before any blocking promotion: a fresh zero-finding result at the existing threshold, a repeat on a settled current checkout, a passing canonical CI run, and explicit evidence that relevant integration/acceptance obligations are green or out of scope. The repository's own import-guard promotion from 413 findings to zero is the local precedent (`dev/toolchain.py:354-374`).

### The ADR must choose staged blocking gates and advisory detection policy

The decision is between immediate hard failure, staged promotion with named CI visibility, and permanent advisory reporting. Evidence excludes immediate promotion because it would make the canonical contract permanently red, and excludes permanent advisory treatment for deterministic static rules because it prevents a ratchet from ever holding. The ADR should decide how individual blocking targets are surfaced before promotion and specify that duplication remains advisory pending a false-positive adjudication contract.

## Sources

- `dev/toolchain.py:1-33`
- `dev/toolchain.py:260-399`
- `dev/toolchain.py:456-541`
- `dev/toolchain.py:544-650`
- `justfile:63-68`
- `.github/workflows/test.yml:42-46`
- `Y:/code/vaultspec-core-worktrees/main/dev/toolchain.py:194`
- `Y:/code/vaultspec-core-worktrees/main/.github/workflows/ci.yml:116`
- `Y:/code/vaultspec-rag-worktrees/main/justfile:113`
- `Y:/code/vaultspec-rag-worktrees/main/.github/workflows/ci.yml:78`
