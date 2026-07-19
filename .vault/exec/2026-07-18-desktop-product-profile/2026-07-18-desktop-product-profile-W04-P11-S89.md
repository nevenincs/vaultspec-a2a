---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S89'
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
     The S89 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Audit and harden ACP terminal children to inherit the owning run containment and bounded reaper and ## Scope

- `src/vaultspec_a2a/providers/_acp_rpc_handlers.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Audit and harden ACP terminal children to inherit the owning run containment and bounded reaper

## Scope

- `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`

## Description

- Audit finding: `on_terminal_create` spawned each ACP terminal child directly
  via `asyncio.create_subprocess_exec` with `CREATE_NEW_PROCESS_GROUP` on Windows
  but `creationflags=0` and no new session on POSIX. The child carried no
  containment, so `_kill_process_tree` fell back to the per-pid kill - which on
  POSIX signals only the single pid and orphans any grandchild a terminal shell
  spawns. The children were tracked in `ctx.terminals` and reaped on
  kill/release/session-teardown, but not as a bounded, discovery-free tree.
- Harden: seat every terminal child in its own `ProcessContainment` before it
  runs (POSIX new session/process group; Windows Job Object assigned after
  spawn, keeping `CREATE_NEW_PROCESS_GROUP`), stash it on the process under the
  shared `_CONTAINMENT_ATTR` so the existing `_kill_process_tree` reaps the whole
  terminal subtree through the containment. A Windows assignment failure
  downgrades to the per-pid fallback with a logged warning.
- Prove it with a real terminal subtree
  (`providers/tests/test_terminal_containment.py`, service-marked): a terminal
  child created through `on_terminal_create` plus the grandchild it spawns are
  reaped whole by `on_terminal_kill` via the containment.

## Outcome

ACP terminal children inherit their own OS containment and are reaped as a
bounded, discovery-free tree on every terminal path. Gates: `ruff check`/`format`
clean, `ty check` clean on `_acp_rpc_handlers.py` and the test. New test:
`test_terminal_containment.py` = 1 passed under `-m service`. Providers suite
`pytest providers` = 342 passed, 10 deselected; existing terminal allowlist /
metacharacter rejection tests unchanged.

## Notes

The terminal child is a child of the worker (it answers the CLI's RPC), not of
the ACP provider root, so it inherits the run containment as its OWN job/group
rather than joining the provider job; on the armed desktop it also auto-joins the
worker job, so it is reaped at both run-terminal and worker shutdown. The
containment rides on the process via the same attribute the provider reaper reads
(`_subprocess._CONTAINMENT_ATTR`), single-sourced rather than restated.
