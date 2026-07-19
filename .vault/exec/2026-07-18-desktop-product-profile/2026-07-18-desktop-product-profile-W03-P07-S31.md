---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S31'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S31 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Replace token-bearing discovery with an atomic versioned profile generation protocol schema owner and ACL-reference record and ## Scope

- `src/vaultspec_a2a/lifecycle/discovery.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Replace token-bearing discovery with an atomic versioned profile generation protocol schema owner and ACL-reference record

## Scope

- `src/vaultspec_a2a/lifecycle/discovery.py`

## Description

- Add the versioned, secret-free desktop discovery record to
  `lifecycle/discovery.py` alongside the existing Compose record, which stays
  untouched so its consumers keep working.
- Introduce `DesktopDiscoveryRecord` carrying record version, `desktop` profile,
  generation identity, protocol range, process identity (pid plus the runtime
  singleton's start fingerprint), loopback endpoint, freshness stamp, owner
  identity, and a non-secret credential-file reference — never a bearer value.
- Publish atomically (temp write, fsync, rename) with a bounded retry that rides
  out a transient Windows sharing-violation on rename without ever exposing a
  partial record.
- Parse fail-closed: an absent or unknown version, a non-`desktop` profile, or a
  missing identity or endpoint field yields no record and classifies malformed.
- Classify a record filesystem-only (fresh, stale, malformed, absent) reusing
  the shared freshness contract, and prove a recorded process dead through the
  runtime singleton's start-fingerprint authority.
- Add real tests: field round-trip, a byte-level scan proving no environment or
  credential-file secret reaches the published record, freshness and
  malformation classification, process liveness, and a racing-reader atomicity
  proof against repeated real writes.

## Outcome

The desktop discovery record is versioned, owner-attributed, and carries no
bearer value. Gates: `ruff` and `ty` clean; the new suite passes;
`pytest src/vaultspec_a2a/lifecycle -q` 117 passed. `S32` teaches the
dashboard-facing reader to parse this shape without weakening engine authoring
discovery; `S33` publishes it from the singleton owner after listener bind.

## Notes

A concurrent authentication campaign holds an uncommitted rewrite of the same
module in the shared working tree (it moves the Compose bearer out of discovery
into an owner-restricted credential file referenced by path). To avoid claiming
that work, only this Step's additive hunks were staged into the index through
`git apply --cached` against `HEAD`; the campaign's working-tree changes were
left in place. The gateway wiring that publishes this record (singleton owner,
post-bind) lands in `S33`; full attach-credential creation lands in `W03.P08`.
