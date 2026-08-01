---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:eae13b81170d7787be24aaf7c595198c3e044e5a5c05dda0a7c8193e90bcb3d6'
step_id: 'S95'
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
     The S95 and 2026-07-19-codebase-health-plan placeholders are machine-filled by
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
     The Prove authenticated two-gateway one-worker pairing with real processes and ## Scope

- `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove authenticated two-gateway one-worker pairing with real processes

## Scope

- `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`

## Description

- Decide and record the profile-split enforcement policy (armed = verdict
  authority; unarmed = legacy signal) in the codebase-health decision record.
- Wire the classifier and eviction authorization into every adoption seam of
  the worker manager; thread the spawner generation through.
- Prove the two-gateway one-worker topology with two complete armed gateways
  over separate migrated application homes sharing one worker port: gateway A
  spawns and owns its real worker (prepare 201); gateway B's demand is
  refused (503, not execution-ready).

## Outcome

Proven with real processes. B never adopts and never evicts: A's worker
still answers on the port after B's attempt, and B's log carries a
provenance-shaped refusal. The proof surfaced a second, earlier fail-closed
layer: A's worker rejects B's health probe outright (401) because the
worker-IPC credential is application-home-scoped, so a foreign gateway
cannot even read the pairing evidence - defence in depth ahead of the
classifier.

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
