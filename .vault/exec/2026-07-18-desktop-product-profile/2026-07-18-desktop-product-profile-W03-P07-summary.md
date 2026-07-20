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

# `desktop-product-profile` `W03.P07` summary

Phase P07 established desktop runtime identity: an operating-system-held
lifetime singleton guards one app home, discovery is a versioned, atomically
published, secret-free record, the authoring reader parses both record
generations, singleton acquisition precedes listener bind, and two real-
process certification gates prove exclusion, stale recovery, and immutable
live-conflict behavior. All six Steps (S30 through S35) are closed;
independent review passed after one high finding was remediated.

- Modified: `src/vaultspec_a2a/lifecycle/discovery.py`,
  `src/vaultspec_a2a/authoring/discovery.py`, `src/vaultspec_a2a/cli/main.py`
- Created: `src/vaultspec_a2a/lifecycle/singleton.py`,
  `src/vaultspec_a2a/desktop_tests/test_runtime_singleton.py`,
  `src/vaultspec_a2a/desktop_tests/test_discovery_ownership.py`

## Description

S30 implemented the cross-platform runtime singleton: an exclusively held
byte-range lock that dies with the process, an atomic owner record carrying a
process-start fingerprint that guards against pid reuse, held, stale,
foreign, malformed, and free classification, owner-only stale takeover
serialized by the lock itself, and bounded retry over orphaned locks. S31
added the versioned desktop discovery record — version, profile, generation,
protocol range, process identity, endpoint, freshness, owner, and a
non-secret credential-file reference — published atomically beside the
untouched legacy record, with a byte-scan proof that no secret reaches the
published form. S32 taught the authoring reader to parse both record
generations fail-closed, skipping bearer-less records for engine resolution
so existing engine flows are unchanged. S33 ordered singleton acquisition
before the gateway's socket bind under the armed profile, holding it for the
process lifetime with release on shutdown, and failing loud with the
immutable-conflict classification for a live foreign resident; versioned-
record publication after bind remains an explicit seam for the credential
phase, which also adds attach authentication. S34 and S35 certify the state
machine with real child processes: a second gateway cannot own or corrupt an
owned app home, an owner-matching restart reclaims a genuinely dead
holder, a foreign contender can validate but never own, and incompatible or
malformed residents produce immutable conflicts, with ownership always
proven through the published record rather than launch handles.

## Tests

The lifecycle suite (117 passed), authoring suite (109 passed), the new
real-process certification gates, and the CLI singleton tests are green, all
with real child interpreters, real kills, real locks, and real credential
files; no fakes, mocks, stubs, patches, monkeypatches, skips, or expected
failures. Review passed after remediation stripped plan coordinates from a
certification docstring and replaced a short-circuiting environment scan
with a genuine no-secret assertion. The single desktop-baseline failure at
review time was attributed to a concurrent session's uncommitted manifest
churn, outside this phase's commits.
