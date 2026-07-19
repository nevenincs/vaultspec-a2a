---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---




# `desktop-product-profile` `W02.P05` summary

Phase P05 separated schema validation from migration: ordinary armed desktop
boot never mutates a schema, and the external updater owns migration through a
one-time transaction descriptor and a dedicated staged-generation entrypoint.
All five Steps (S20 through S24) are closed; independent review returned PASS
and its one code-level medium finding was remediated in a follow-up fix.

- Modified: `src/vaultspec_a2a/api/app.py` (armed gating seam),
  `src/vaultspec_a2a/database/` (compatibility validation),
  `src/vaultspec_a2a/cli/main.py` (internal desktop-migrate command)
- Created: `src/vaultspec_a2a/desktop/transaction.py`,
  `src/vaultspec_a2a/desktop/migration.py`,
  `src/vaultspec_a2a/desktop_tests/test_migration_entrypoint.py`

## Description

S20 gated every boot-time schema mutation site (Alembic upgrade, checkpointer
setup, and structured-decision-data backfill) behind a single armed-profile
seam; armed boot instead runs read-only compatibility validation whose
supported range derives from the migration script directory, never a
hardcoded revision, and whose non-mutation is proven by full schema-dump
equality. Unarmed Compose and development boot is byte-for-byte unchanged.
S21 added the updater's one-time transaction descriptor: file-based,
single-use, validated against the armed profile's state roots and the
package's migration range, failing closed with typed errors. S22 implemented
the staged-generation migration entrypoint that refuses live or locked stores
via a real locking probe, runs the Alembic upgrade, checkpointer setup, and
backfill in order against descriptor-named stores only, and returns a bounded
machine-readable result; a review remediation wrapped every exit path,
including post-mutation consume failures, in that result contract. S23
exposed the internal desktop-migrate command on the CLI only, with a real
test proving the run-control HTTP surface gained no route. S24 certifies the
whole path from a clean installed capsule: a real wheel installed into a
fresh environment migrates a fresh app home to head and rejects an
incompatible range, a consumed descriptor, and a live store.

## Tests

Twenty-six unit and CLI tests plus a four-test installed-capsule service gate
pass, all against real SQLite stores, real cross-process locks, real files,
and real child processes; no fakes, mocks, stubs, patches, monkeypatches,
skips, or expected failures. The remediation suite adds a real post-mutation
consume-failure case proving JSON-shaped failure instead of a traceback.
Review follow-ups tracked elsewhere: the Windows descriptor
permission-enforcement gap closes under the credential-boundary phase, and an
unrelated gateway-authentication edit bundled by a concurrent session into
one commit is attributed to that campaign.
