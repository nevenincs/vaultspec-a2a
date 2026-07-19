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

### implicit-tooling-profile | high | Initial native recipes relied on ambient tooling packages

Type: dependency authority. The first S06 code and test modules used frozen
`uv run` commands without selecting the `tooling` group even though the project
declares no default groups. The shared environment masked the fresh-clone
failure. Status: resolved in S06 by adding explicit no-default-group tooling or
development profile selection and proving the packages in an isolated run.

### build-clean-venv-scope | high | Initial cleanup discovery could enter the project virtual environment

Type: destructive-path safety. The first S06 cleanup recipe recursively found
egg metadata from the repository root, which could include the project virtual
environment. Status: resolved in S06 before execution by limiting discovery to
explicit source, test, and documentation roots and retaining an absolute
repository-boundary check before every recursive removal.

### native-module-version-check | medium | Installed Just rejected the documented minimum-version setting

Type: compatibility drift. The initially researched setting was not accepted by
the installed Just 1.46 parser. Status: resolved in S06 by keeping an actionable
root requirement notice and adding a real PowerShell version comparison to the
doctor; Just 1.46.0 satisfies the stable-module minimum of 1.31.0.

### nested-help-option-order | low | Initial developer help passed the module outside the list option

Type: command usability. The first `just dev` run rejected the list command
because its module argument followed another option. Status: resolved in S06 by
binding `dev` directly to `--list`; root and nested help now execute and list all
submodules.

### hook-validation-mutation | medium | Current hook pipeline is not yet a read-only validator

Type: contract debt. S06 preserves hook install, removal, execution, and explicit
repair entry points but deliberately does not describe the current `prek`
pipeline as read-only because its configuration still contains mutating
Vaultspec hooks. Status: open and queued for S08, which owns hook validation and
repair separation.

### test-selection-name-drift | medium | The all-test recipe still inherits the non-service default marker

Type: test contract debt. S06 preserves the current Pytest selection while
making its recipe description honest; the project-level default still excludes
service tests, so `all` is not yet semantically complete. Status: open and
queued for S09 test-selection remediation.

## Recommendations

No open task remains for S01, S02, or the S03 implementation. Preserve the two
S02 corrections when the modules are imported by the root Justfile, retain the
S03 exact-version runtime contract during dependency upgrades, and retire the
inherited MCP test shortcuts in S09.

Keep the newly trackable canonical `.vaultspec` and provider projections in
S05 scope, while classifying the exposed runtime and lock surfaces separately.
Resolve whether Core should expand its managed policy before adding any exact
repository stopgap, so Core remains the single framework-ignore owner.

Preserve S06's explicit dependency groups and cleanup boundary. Complete named
service and stack ownership in S07, make hooks read-only in S08, and correct the
project-wide test selection in S09 before promoting those surfaces into the
terminal CI contract.
