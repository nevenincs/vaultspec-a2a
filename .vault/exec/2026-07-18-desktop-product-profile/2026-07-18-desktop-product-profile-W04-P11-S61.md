---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S61'
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
     The S61 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Terminate owned POSIX process groups with bounded killpg SIGTERM-to-SIGKILL escalation and assigned Windows Job Objects or equivalently proven OS-owned jobs or trees without recursive process discovery and ## Scope

- `src/vaultspec_a2a/utils/process.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Terminate owned POSIX process groups with bounded killpg SIGTERM-to-SIGKILL escalation and assigned Windows Job Objects or equivalently proven OS-owned jobs or trees without recursive process discovery

## Scope

- `src/vaultspec_a2a/utils/process.py`

## Description

- Finalize the bounded, discovery-free termination contract of
  `ProcessContainment.terminate` in `utils/process.py`. The POSIX path already
  escalates `killpg` SIGTERM -> (bounded wait) -> SIGKILL over the owned process
  group; make the Windows path symmetrically bounded and confirmed.
- Replace the immediate `TerminateJobObject`-and-return with a bounded wait that
  polls the job's own active-process count (`QueryInformationJobObject` /
  `JobObjectBasicAccountingInformation`) until it reaches zero or `kill_timeout`
  elapses, so terminate returns only once the WHOLE contained tree is gone - not
  just the root the caller separately waits on - and never by walking parent
  pids. A query failure resolves as "empty" so the wait is always bounded.
- Prove the discovery-free property with a real subprocess tree
  (`utils/tests/test_process_containment.py`): assign the containment, gate the
  grandchild spawn behind a stdin signal so it provably joins the containment,
  then KILL the intermediate parent directly (severing the parent-pid link a
  recursive `taskkill /T` walk needs) and show `terminate` still reaps the
  orphaned grandchild via job / process-group membership.

## Outcome

Owned roots terminate with bounded escalation and no recursive process
discovery; the Windows job path now confirms the tree is empty before returning.
Gates: `ruff check`/`format` clean, `ty check` clean on `utils/process.py`. New
test: the orphaned-descendant discovery-free proof passes (5 passed in the
containment module, real Windows Job Object trees). Closeout suite `pytest api
control worker providers utils` = 926 passed, 17 deselected.

## Notes

The bounded-escalation implementation was introduced with the primitive in
`W04.P11.S59` (the worker needed bounded shutdown at that Step); this Step
finalizes the contract - the Windows confirmed-empty wait and the discovery-free
proof - as the termination authority the Phase's owned roots (`S59` worker,
`S60` provider) already route through. The recursive `taskkill /T /F`
(`kill_pid_tree_async`) remains only as the explicit fallback for a process
without a containment and for the unchanged Compose/development per-pid path; no
armed-desktop owned root depends on it. POSIX escalation is correct by
construction but unexercised on this Windows host (POSIX CI covers it).
