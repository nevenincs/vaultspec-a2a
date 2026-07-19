---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- PHASE SUMMARY:
     This file rolls up every <Step Record> belonging to one Phase
     of the originating plan. Each Step (S##) in the Phase produces
     one <Step Record> in `.vault/exec/`; this summary aggregates
     them, lists modified / created files across the Phase, and
     reports verification status. -->

# `desktop-product-profile` `W02.P06` summary

Phase P06 delivered the snapshot and restore consistency-group primitives the
dashboard's external updater depends on, and bound mutable-store membership
into the component manifest. All five Steps (S25 through S29) are closed;
independent review's one high finding and all lower findings were remediated.
With P04, P05, and P06 complete, Wave W02 — transactional desktop state — is
done.

- Modified: `src/vaultspec_a2a/cli/main.py`,
  `src/vaultspec_a2a/desktop/contract.py`,
  `src/vaultspec_a2a/desktop/manifest.py`,
  `schemas/desktop-capsule-manifest.json`
- Created: `src/vaultspec_a2a/desktop/snapshot.py`,
  `src/vaultspec_a2a/desktop_tests/test_snapshot_group.py`,
  `src/vaultspec_a2a/desktop_tests/test_snapshot_recovery.py`

## Description

S25 implemented the consistency-group module: the primary and checkpoint
databases are captured coherently through the SQLite online-backup interface,
staged to temp files with fsync discipline honest about platform limits, and
committed by one atomic group descriptor carrying per-store digests and
schema facts; restore is governed by a quiesced marker written before any
store is touched and cleared only after every store is restored and synced,
with idempotent roll-forward resume from immutable copies and fail-closed
refusal of live or locked stores. S27 exposed bounded snapshot create,
inspect, and restore commands on the CLI only, always returning
machine-readable results. S28 certifies that both databases of a real
migrated group restore together; S29 constructs the real on-disk states of
every interruption boundary and proves detection, refusal, recovery, and
that no half-restored pair is ever reported healthy. S26, deferred until a
concurrent migration-head landing settled, bound mutable-store membership and
derivability into the component manifest under a contract version bump to
1.1, with the schema snapshot and cross-language golden vector regenerated
from the settled head and a reconciliation test pinning manifest membership
to the runtime group declaration. Review remediation stripped a plan-step
identifier from source, added mismatched-resume refusal, cleaned error-path
temp sidecars, and strengthened the all-or-nothing certification.

## Tests

Twenty-two snapshot-surface tests plus nine new contract tests pass against
real WAL-mode SQLite stores, real migrations, real lock holders, and real
crash-boundary states; the full desktop baseline stands at 242 passed with
service gates deselected, and the head-archive component-contract gate passes
against the regenerated schema generation. No fakes, mocks, stubs, patches,
monkeypatches, skips, or expected failures anywhere in the phase. One
staging incident — a whole-file plan add briefly sweeping a sibling wave's
uncommitted row state — was detected, corrected in a follow-up commit, and
converted into hunk-isolation staging discipline for the shared plan file.
