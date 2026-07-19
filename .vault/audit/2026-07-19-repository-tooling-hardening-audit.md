---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
related: []
---

# `repository-tooling-hardening` audit: `rolling implementation review`

## Scope

Review each implementation Step against the accepted ADR, implementation plan,
and provisioning reference. The rolling audit covers dependency authority,
command ownership, Windows portability, governance convergence, validation,
hosted security, documentation, and close-out behavior.

## Findings

S01 dependency-profile and lockfile review passed with no findings.

### rag-install-mode | medium | RAG recipe used an unsupported public install flag

The initial S02 recipe passed Core's `--mode dependency` spelling to
`vaultspec-rag install`, whose 0.3.2 public help does not expose that option.
The real dry-run would have failed. Status: resolved in S02 by removing the
flag and allowing RAG to detect the project dependency placement.

### windows-module-shell | medium | Standalone modules selected Git Bash on Windows

The first direct-module verification emitted an `/etc/bash.bashrc` error
because standalone Just modules inherited the default shell. Status: resolved
in S02 by declaring native no-profile PowerShell in every module and rerunning
the real previews without the Bash startup error.

## Recommendations

No open task remains for S01 or S02. Preserve the two S02 corrections when the
modules are imported by the root Justfile and recheck them during final review.
