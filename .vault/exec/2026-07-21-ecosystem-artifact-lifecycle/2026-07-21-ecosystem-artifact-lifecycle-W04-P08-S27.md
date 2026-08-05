---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-08-04'
modified: '2026-08-04'
body_schema: 'body-v1'
body_hash: 'sha256:b1c456453ea3364642d3e63f063100cb6ef1f3fa94b5d43e77fbee28c4185433'
step_id: 'S27'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace ecosystem-artifact-lifecycle with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S27 and 2026-07-21-ecosystem-artifact-lifecycle-plan placeholders are machine-filled by
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
     The Declare or refuse a retention statement for each lane's persistence, through the existing artifact declaration home and ## Scope

- `src/vaultspec_a2a/artifacts/retention.py`
- `src/vaultspec_a2a/providers/_config_home_roots.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Declare or refuse a retention statement for each lane's persistence, through the existing artifact declaration home

## Scope

- `src/vaultspec_a2a/artifacts/retention.py`
- `src/vaultspec_a2a/providers/_config_home_roots.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Declare the ACP session transcript at the seam that causes it, through the
  existing artifact declaration home rather than a new mechanism.
- Declare the Gemini and Kimi session stores and name their producer.
- Reconcile a conflict between the declaration's stated premise and the measured
  orphan shape, from source rather than by choosing one account.
- Add a guard requiring every session-opening seam to name the declaration, and
  act on the seam it found.

## Outcome

**Declared, not reclaimed - and the reconciliation changed what the declaration
says.**

Three lanes now carry declarations at the seams that cause them: the ACP CLI
session transcript, the Gemini session store, and the Kimi session store, beside
the pre-existing per-run Codex home and ephemeral home root. Declaration was
chosen over reclamation because nothing in this project creates, names, opens, or
can reach these files; suppression at the seam is available and deletion is not.

The correction is the substance. The first declaration said a run mints no new
partition. That was true and misleading, and it did not describe what
accumulates. Established from source: catalog discovery issues a real session
open with the caller's working directory, so the prompt-free probe partitions the
operator's config home exactly as a run's session does - and it is the
HIGHER-frequency seam, because one catalog read probes every registered lane
while a run spawns only the lane it selected.

So the orphan condition is not which seam opened the session. Neither mints a
partition per run; both mint one per WORKSPACE, and a partition orphans exactly
when the directory it keys stops existing. Served production hands both seams the
operator's own project, which persists. A caller that mints a fresh workspace per
invocation collapses per-workspace into per-invocation, and that is the measured
accumulation. **It is a property of the CALLER's workspace lifetime, not of the
lane** - which is why the remedy is not in the provider code at all.

An exists-check on the keyed directory does not rescue reclamation, and the
reason is recorded with the declaration: an operator who deletes a scratch
directory they worked in leaves an orphan of their own, indistinguishable from
one of ours.

The guard requiring every session-opening seam to name its declaration
immediately found a seam that had been missed - the run's own session open lives
in the session module rather than the chat model - which is the drift such a
guard exists to catch, caught on its first run.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

The config-only precheck that would have shrunk the fan-out is REFUSED, on
measurement rather than taste. Every lane with a genuine definitely-absent signal
already exits without spawning today. The remaining case - CLI installed, ambient
or persisted authentication, no explicit credential in settings - is the normal
state of three lanes on a working machine, and a no-explicit-credential-means-
unavailable gate would report a false unavailable for a lane that genuinely
works on ambient OAuth. That is the precise failure mode the served-profiles rule
exists to prevent.

Measured cost of the fan-out, which reframes the accumulation as the visible
symptom of a larger waste: one catalog read spawns FOUR real external CLI process
trees concurrently, bounded by the slowest lane at roughly fifteen seconds. A
five-minute catalog cache already exists and is keyed by workspace root, so it
would collapse this to a single spawn - and never does, because every caller in
the test tier mints a fresh root. The waste and the accumulation have one cause.

NOT actioned here, and the highest-value remaining work on this trail: giving the
test-tier callers a shared or stable workspace root. That collapses hundreds of
uncached fan-outs into one and stops minting orphans, without touching the
production contract that discovery must root at the run's real workspace.
