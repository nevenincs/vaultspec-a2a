---
tags:
  - '#audit'
  - '#desktop-product-profile'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:ca7f1a9700e8b83abcb2bfbcd40b8c85e0c5404024d0bad8732c5db71fd78616'
related:
  - "[[2026-07-18-desktop-product-profile-adr]]"
  - "[[2026-09-23-project-bound-state-adr]]"
---

# `desktop-product-profile` audit: `Sensitive desktop state permission remediation`

## Scope

Authorized by the user's explicit 2026-10-04 fix request for the low-severity scan finding observed at revision b973403. Reviewed desktop profile setup, environment-armed store preparation, standalone setup/migration, permission helpers, and focused regressions. Direct maintenance under the accepted desktop and project-state decisions; no new costly decision or implementation plan is needed. Unrelated concurrent work is excluded. Discovery used Core search and the all-feature ADR listing; code semantic search returned non-authoritative index_unverifiable, so code grounding used direct reads and targeted searches.

## Findings

### permission-hardening-fails-open | low | Resolved: sensitive desktop state now fails closed

Type: security/confidentiality. Status: resolved. The original profile swallowed OSError while restricting database directories. `src/vaultspec_a2a/desktop/profile.py:413` now enforces verified owner-only permissions on the home, provisioned directories, both databases, and existing -wal, -shm, and -journal files. Unsupported filesystems are refused. No insecure-state override is provided. Directory privacy protects future side files; existing Windows files with independent broad ACLs are explicitly restricted.

### environment-armed-desktop-bypass | low | Resolved: store preparation verifies privacy before SQLite opens

Type: security/enforcement coverage. Status: resolved. Settings previously seated desktop paths without invoking profile setup. `src/vaultspec_a2a/control/config.py:278` now invokes the shared private-state authority on the armed, home-relative preparation branch used by database and checkpoint opening. Configuration construction remains free of filesystem writes, and non-desktop preparation retains its prior behavior.

### standalone-lifecycle-bypass | high | Resolved: setup and migration share the protection boundary

Type: security/incomplete remediation boundary. Status: resolved after independent candidate review. The reviewer granted Everyone access to a temporary Windows home and reproduced initialize_fresh_stores succeeding while home, state, and both databases remained public. `src/vaultspec_a2a/desktop/migration.py:307` and its public entrypoints now verify private state before revision reads or mutations and recheck newly created files before success. Refusals preserve the structured failed/precondition result. Native ACL-denial and linked-directory lifecycle regressions prove refusal precedes database creation.

### sqlite-side-file-disappearance | medium | Resolved: ordinary SQLite cleanup does not cause false refusal

Type: compatibility/availability. Status: resolved after independent candidate review. Concurrent WAL and rollback-journal writes reproduced files disappearing between inspection and hardening; Windows can also report a delete-pending regular side file with zero links. `src/vaultspec_a2a/desktop/profile.py:375` tolerates absent/deleted ephemeral side files beneath an already private parent. Present files still require verified permissions and must be regular and single-linked. Directories and persistent databases retain fatal error handling. The effective Windows state predicate accepts private inherited ACEs on newly created SQLite side files; credential readers retain strict publication checks. Real threaded regressions repeatedly open, commit, and close SQLite while preparing state and verify every written row remains present.

### ineffective-posix-permission-check | low | Resolved: effective ownership and modes are read back

Type: security/verification. Status: resolved. POSIX chmod had no readback, and the original directory test called a Windows predicate that always returned true on POSIX. `src/vaultspec_a2a/desktop/_platform_acl.py:257` now verifies current-effective-user ownership and 0700/0600 modes or effective native Windows permissions. Updated tests exercise real filesystem permissions on both platforms.

### linked-or-foreign-owned-state | low | Resolved: aliases and foreign Windows owners cannot satisfy privacy

Type: security/alias and owner-authority coverage. Status: resolved. Linked directories, symbolic links, junctions, nonregular stores, and hard-linked database/side files are refused before permission mutation. Windows owner SID readback also rejects a foreign owner who could replace an otherwise private DACL. A native foreign-owner probe confirmed refusal despite private allow ACEs, then restored the original owner. Real tests reject planted links and repair Everyone-readable existing files without changing their contents.

## Recommendations

Scoped final review: PASS after correcting both independently confirmed candidate findings. No open finding remains within this remediation. Retain the real privacy and SQLite-churn tests as regression coverage. Continue native target certification under the existing desktop release process; macOS was not executed in this session.

Verification uses the current seven source/test files in the shared working tree. Windows coverage spans 110 distinct tests across profile, state security, credentials, migration, opened-secret confirmation, desktop CLI, desktop settings, state sealing, and discovery. An initial churn failure was fixed; the final state-security/migration rerun passed all 30 tests and the unchanged passing cases remain applicable. Linux passed 101 applicable tests in Docker with CPython 3.13 and the repository's frozen tooling profile. The Windows-specific opened-secret module was excluded from the Linux invocation; no tests, mocks, skips, or expected failures were added to bypass evidence.

Commands: `uv run --no-sync python -m vaultspec_a2a.testing.runner -- <focused suites> -q`; Linux uses `uv run --frozen --group tooling python -m vaultspec_a2a.testing.runner -- <applicable suites> -q -o cache_dir=.pytest-tmp/linux-security-cache`. Changed-file Ruff lint/format, Ty, and strict BasedPyright pass. A read-only Linux bind-mount probe confirms failed chmod stops setup before SQLite creation. Native Windows WRITE_DAC-denial tests confirm setup and lifecycle refusal, followed by recovery after ACL restoration. Fresh and repeated setup, migrations, credential readers, and real SQLite reads/writes remain successful. Initial Linux tooling lacked Git and an earlier run warned about the existing pytest cache; the final container installed Git and used an isolated ignored cache, producing a clean run.

Final isolation check: the nine-file patch was copied to `Y:/code/vaultspec-a2a-worktrees/desktop-private-state` on branch `fix/desktop-private-state`, preserving all concurrent source and staged changes in the main worktree. Only the six-line desktop preparation hunk from `control/config.py` was included. The complete Windows suite then passed all 110 tests in one run against that isolated patch; strict BasedPyright also passed there. Linux's 101-test evidence and both real filesystem refusal probes remain applicable to the unchanged permission/profile/migration files.
