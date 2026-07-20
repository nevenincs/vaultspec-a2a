---
tags:
  - '#audit'
  - '#desktop-product-profile'
date: '2026-07-18'
modified: '2026-07-18'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `desktop-product-profile` audit: `review`

## Scope

The mandatory final architecture, security, resource-bound, and real-behavior
review of the entire desktop-product-profile implementation, performed by an
independent reviewer persona as a consolidating pass over the thirteen
already-cleared phase reviews. Epicenters read in full across the five
architecture pillars: the capsule and component-manifest contract
(`src/vaultspec_a2a/desktop/contract.py`, `manifest.py`, the schema
snapshot, and the builder and verifier scripts), transactional state
(`profile.py`, `transaction.py`, `migration.py`, `snapshot.py`), runtime
identity and credentials and readiness (`lifecycle/singleton.py`,
`lifecycle/discovery.py`, `desktop/credentials.py`, `control/health.py`),
process and run ownership (`control/drain.py`, `control/admission.py`,
`desktop/settlement.py`, `utils/process.py`), and the certification suites
with their continuous-integration wiring.

Verdict: PASS. No critical or high findings. Safe to merge; release remains
gated on the honestly registered owner and continuous-integration residuals
recorded in the certification audit.

## Findings

### architecture-coherence | low | Five pillars match the decision record with coherent cross-pillar seams

The manifest consumes the snapshot module's consistency-group specifications
as the single membership authority, so the manifest and the capture set
cannot drift. The profile's derived state paths are the sole layout
authority consumed by snapshot, settlement, and credentials with no parallel
path arithmetic. Admission mints the non-secret lease handle that settlement
later carries, verified as the same identity. The singleton is acquired
before listener bind, discovery publishes a secret-free record naming an
access-restricted token handoff, and the three credential planes are
enforced non-interchangeable in code paths, not only in tests.

### security-posture | low | Constant-time comparison and no-secret discipline hold across the surface

Every credential comparison routes through constant-time helpers; a sweep
found no data-dependent secret compare, no secret logging, and no credential
value in any serialized output. The desktop gateway binds loopback only.

### resource-bounds | low | Every resource-bearing path is bounded or explicitly justified

Settlement retries, admission reservations and their expiry sweep, drain
waits, singleton lock reclaim, and snapshot temporary staging are all
bounded; indefinite waits exist only behind explicit caller-supplied
unbounded timeouts, matching the decision record's transaction ownership.

### real-behavior | low | Certification suites are honest and reproducibly green

Suite-honesty audit found no expected failures or monkeypatching; the only
skips are the tracked platform-capability pair owned by an open follow-up
row, and service gates deselect rather than skip. The reviewer's own runs:
32 passed non-service desktop gates, 5 passed dependency-closure gates, 364
passed with 1 tracked skip in the module-local desktop suites, and 519
passed across the api, control, and worker suites.

### standalone-adapter-bind | low | The caller-owned adapter's default bind is non-loopback

The standalone adapter's host setting defaults to all interfaces. The
adapter is caller-owned and outside the desktop gateway boundary, so this is
not a desktop-listener violation, but the default deserves a one-line owner
confirmation that the non-loopback surface is intended.

## Recommendations

Confirm the standalone adapter's default bind intent (tied to the
standalone-adapter-bind finding). Exercise the POSIX containment paths and
the five per-target capsule legs on hosted runners before release (tied to
the residual register in the certification audit). No revision to the
implementation is required.
