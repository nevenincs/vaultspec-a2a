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

### s05-runtime-staging-escape | high | Recursive shared staging included excluded runtime evidence

Type: process safety and repository hygiene. During S05, the shared index
contained `.vaultspec/runtime/` evidence and `.qdrant-initialized` even though
the Step explicitly excluded runtime, cache, and machine state. Status:
resolved before commit by unstaging only those paths, verifying provider lock
files remained untracked, and requiring a zero-match safety scan of the final
commit inventory. No runtime, lock, secret, cache, or Qdrant path was committed.

### s05-rule-format-conformance | low | Initial retained rule bodies needed Markdown normalization

Type: documentation quality. The first compact canonical bodies were valid but
failed the repository's `mdformat --check` gate. Status: resolved in S05 by
formatting in memory, writing the normalized bodies back through Core's owning
rule verb, regenerating every provider projection, and rerunning the check.

### core-runtime-ignore-ownership | medium | Core exposes no owning configuration for uncovered runtime locks

Type: upstream contract gap. S05 confirmed that Core 0.1.48 has no rule or
configuration verb that extends its managed Git-ignore policy for
`.vaultspec/runtime/`, `.agents/mcp_config.json.lock`, or
`.codex/config.toml.lock`. Status: open upstream; S05 leaves the paths untracked
and unstaged rather than adding a competing repository-owned framework rule.

### core-builtin-content-skew | medium | Locked Core reported nine canonical builtins older than its package

Type: version and generated-content drift. Core 0.1.48 initially reported that
nine canonical builtins, including `rules/vaultspec.builtin.md`, were older
than the installed package. Status: resolved in S05 through a previewed and
then applied project-locked `install all --upgrade`; the owning operation
updated four agents, the CLI reference, one built-in rule, one skill, and two
system sources. A second upgrade preview reported every framework asset
unchanged, while complete provider sync and rule status proved convergence.

### s05-install-mode-drift | medium | Workspace metadata recorded floating tool launch modes

Type: dependency placement and reproducibility. The provisioned workspace
metadata initially recorded both Core and RAG with `install_mode: tool`, which
contradicted the repository's project-locked development and runtime dependency
profiles. Status: resolved in S05 through the owning locked installers: Core
0.1.48 converged with `--mode dev`, and RAG 0.3.2 converged with
`--mode dependency --upgrade --no-mcp --no-provision --no-torch-config --yes`.
The RAG optional dependency profile already supplies its MCP extra, so
`--no-mcp` disables duplicate dependency acquisition without removing runtime
capability. The resulting metadata records `dev` for Core and `dependency` for
RAG without downloading models or Qdrant.

### s05-rag-base-dependency-regression | high | MCP acquisition duplicated RAG into base dependencies

Type: dependency-profile integrity. The first dependency-mode RAG enrollment
used `--mcp`, which invoked dependency acquisition and added an unbounded
`vaultspec-rag[mcp]>=0.3.2` base dependency beside the approved optional
`rag = ["vaultspec-rag[mcp]>=0.3.2,<0.4"]` profile. Status: resolved before
commit by removing only the newly added base entry, regenerating `uv.lock`, and
using `--no-mcp` for idempotent enrollment because the synchronized `rag` extra
already provides MCP. A real owning install preserved dependency-mode workspace
metadata and left both `pyproject.toml` and `uv.lock` byte-identical; locked RAG
0.3.2, the `mcp` import, and `server doctor` all resolved successfully.

### s05-rag-mode-help-correction | medium | Earlier audit evidence misclassified a supported RAG flag

Type: audit accuracy and CLI contract. The S02 audit stated that RAG 0.3.2 did
not expose `--mode`, but the actual project-locked 0.3.2 help used in S05
explicitly supports `--mode [tool|dependency|dev]`. Status: resolved in S05 by
retaining the historical finding, appending this correction, and updating the
RAG setup, install, dry-run, and upgrade recipes to declare dependency mode
explicitly while using `--no-mcp` to preserve the existing optional dependency
profile. Real owning installer previews and application replaced the prior
assumption.

### postgres-overlay-composition | high | Initial database stack treated an overlay as standalone Compose

Type: stack contract. The first S07 database recipe referenced the PostgreSQL
overlay alone, and real `docker compose config` rejected its gateway and worker
services because their image/build definitions live in the production base.
Status: resolved in S07 by composing the bounded production base and PostgreSQL
overlay together under an isolated project name; configuration then passed.

### engine-seat-conflation | medium | Initial engine helper forced serve and build repositories to match

Type: process contract. The first named engine recipe reused its serve repository
as `--build-repo`, narrowing a production CLI option that explicitly supports
different source and build trees. Status: resolved in S07 by requiring separate
serve, build, and workspace seats and passing each real option unchanged.

### registry-allocate-omission | low | Initial service module omitted one real registry verb

Type: command completeness. The first S07 surface exposed the requested lifecycle
verbs but omitted the production CLI's safe reservation verb. Status: resolved in
S07 by adding an `allocate ROLE` passthrough and validating it with a dry run.

### dead-process-registry-records | medium | Read-only registry listing found three dead records

Type: operational state. The real S07 `procs list` validation reported two dead
gateway records and one dead worker record. Status: open for an operator to review
and clear explicitly with the registry-owned reap recipe; S07 did not mutate or
delete machine-global process state during validation.

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

Keep the Core runtime-ignore gap upstream-owned and preserve the S05 final
commit inventory gate. Retain the converged Core 0.1.48 framework corpus and
repeat the owning upgrade preview before future framework version changes.

Preserve S07's registry-only host-process boundary and isolated Compose project
names. Review the three dead registry entries before invoking reap, and always
validate the production-plus-PostgreSQL overlay pair together.
