---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S60'
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
     The S60 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Spawn each run-owned ACP or Codex provider root in a POSIX new session and owned process group or an assigned Windows Job Object or equivalently proven OS-owned job or tree before descendant work and ## Scope

- `src/vaultspec_a2a/providers/_subprocess.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Spawn each run-owned ACP or Codex provider root in a POSIX new session and owned process group or an assigned Windows Job Object or equivalently proven OS-owned job or tree before descendant work

## Scope

- `src/vaultspec_a2a/providers/_subprocess.py`

## Description

- Spawn every run-owned ACP/Codex provider root inside its own
  `ProcessContainment` in `providers/_subprocess.py`: `spawn_acp_process` creates
  the containment, merges its POSIX `start_new_session` spawn kwarg (Windows
  keeps `CREATE_NEW_PROCESS_GROUP` and assigns the job after spawn), assigns the
  pid before the CLI launches any MCP bridge or grandchild, and stashes the
  containment on the returned `Process` (a stable attribute) so the shared reaper
  reaches it without changing the chat-model call signatures.
- Reap the whole provider tree through the containment in `kill_process_tree`
  (POSIX process-group killpg escalation / Windows Job Object termination); a
  process without a containment (or whose Windows assignment failed) falls back to
  the shared per-pid tree kill. Update the now-accurate docstrings and the
  strategy log label.
- Downgrade a Windows assignment failure to the per-pid fallback with a logged
  warning rather than failing the spawn.
- Prove the wiring with a real subprocess tree in
  `providers/tests/test_provider_containment.py` (service-marked): a provider
  spawned via `spawn_acp_process` plus the grandchild it spawns are reaped whole
  by `kill_process_tree` through the containment, with no external CLI or mock.

## Outcome

Every run-owned provider root is OS-contained before descendant work and reaped
as one tree on run terminal. Gates: `ruff check`/`format` clean, `ty check` clean
on `_subprocess.py`. New test: `test_provider_containment.py` = 1 passed under
`-m service` (real Windows Job Object provider tree). Closeout suite `pytest api
control worker providers` = 859 passed, 17 deselected (the new service test is
deselected by the default `-m "not service"`, proven explicitly instead).

## Notes

The containment rides on the `Process` via a stable attribute rather than a new
return value or signature change, so `acp_chat_model` and `codex_chat_model` (out
of this Step's scoped file) keep calling `spawn_acp_process`/`kill_process_tree`
unchanged. On the armed desktop the provider is a child of the already-contained
worker, so its job nests inside the worker job (supported on the Windows 11
target); the nested inner job reaps just the one run's provider tree. POSIX
containment is correct by construction but unexercised on this Windows host.
