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

### s03-format-conformance | low | Touched test modules initially needed formatter normalization

The first S03 format check reported both touched test modules as needing Ruff
normalization. Status: resolved in S03 by applying the configured formatter and
rerunning lint and format checks successfully.

### inherited-test-double-debt | medium | Existing MCP tests retain prohibited test shortcuts

The MCP test module predating S03 still imports `FakeListChatModel` and mutates
the shared MCP registry in two fail-closed tests. The new S03 coverage imports
production code directly and runs real subprocesses, so it does not add to this
debt. Status: open and queued for the plan's S09 code-health remediation rather
than widening the locked-runtime Step into unrelated test refactoring.

### runtime-lock-ignore-gap | medium | Core 0.1.48 leaves repository runtime and provider lock state trackable

Type: contract drift. Removing the obsolete broad framework ignores exposed
pre-existing `.vaultspec/runtime/` evidence plus `.agents/mcp_config.json.lock`
and `.codex/config.toml.lock`. Core 0.1.48 correctly owns its marker block and
ignores the canonical snapshots, manifest, ownership record, and vault cache,
but its current managed policy does not cover these three runtime surfaces.
Status: open and queued for S05/upstream reconciliation; S04 does not stage the
exposed runtime or lock files and does not add a competing framework policy.

## Recommendations

No open task remains for S01, S02, or the S03 implementation. Preserve the two
S02 corrections when the modules are imported by the root Justfile, retain the
S03 exact-version runtime contract during dependency upgrades, and retire the
inherited MCP test shortcuts in S09.

Keep the newly trackable canonical `.vaultspec` and provider projections in
S05 scope, while classifying the exposed runtime and lock surfaces separately.
Resolve whether Core should expand its managed policy before adding any exact
repository stopgap, so Core remains the single framework-ignore owner.
