---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:85e69dbd3158f008fcc706a59ae88a908068155fd5d1ec05cc94ed55207a72bf'
step_id: 'S155'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace codebase-health with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S155 and 2026-07-19-codebase-health-plan placeholders are machine-filled by
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
     The Prove unauthenticated legacy readiness never authorizes adoption with real processes and ## Scope

- `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove unauthenticated legacy readiness never authorizes adoption with real processes

## Scope

- `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`

## Description

- Boot a real armed gateway with the worker port held by a stranger
  process echoing this gateway's ``gateway_url`` - the exact legacy readiness
  signal the retired policy adopted on - while carrying no pairing evidence.
- Drive an authenticated prepare and observe the admission surface.

## Outcome

Proven: the echoed URL no longer authorizes adoption - the verdict is
UNIDENTIFIED, the prepare refuses 503, the squatter survives with only
health probes logged. This is the direct proof that the weaker signal was
demoted from authority to irrelevance under the armed profile.

## Notes

The enforcement this proof required did not exist when the Step was
authored: the audit's authenticated-pairing-verdict-not-enforced finding
established the classifier was dead code. The 2026-07-24 codebase-health
decision record made the profile-split policy call, and the enforcement
landed with these proofs in one commit - the verdict now governs the
readiness/adoption gate, the armed pre-spawn occupancy gate, the
non-auto-spawn attach, the post-spawn fallback, and the watchdog's
external-worker fallback, with the spawner's generation threaded into every
call.
