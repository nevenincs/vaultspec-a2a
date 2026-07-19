---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S62'
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
     The S62 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Prove real worker provider terminal authoring projected-project MCP and harness descendants are contained before work and reaped on every graceful and forced terminal path without recursive process discovery and ## Scope

- `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove real worker provider terminal authoring projected-project MCP and harness descendants are contained before work and reaped on every graceful and forced terminal path without recursive process discovery

## Scope

- `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`

## Description

- Add `desktop_tests/test_owned_process_tree.py`, an integrated real-descendant
  proof exercising the production containment seams with REAL subprocess trees.
  The only stand-in is the external provider CLI (not installed): a real Python
  "provider" launched through the genuine `spawn_acp_process` seam spawns three
  real children modelling the authoring-MCP, projected-project-MCP, and
  harness-MCP descendants a real provider launches as its own children.
- Prove the run-owned provider tree is contained BEFORE work (its containment is
  assigned) and reaped WHOLE on the graceful terminal (`kill_process_tree` fells
  the provider plus all three MCP descendants).
- Prove the forced/orphaned terminal: kill only the provider root, orphaning the
  MCP descendants, then reap them via the containment - a discovery-free reap
  that a parent-pid tree walk could no longer perform.
- Prove the run-owned terminal child tree through the genuine
  `on_terminal_create`/`on_terminal_kill` seam (child plus grandchild reaped as
  one).
- Prove the gateway-owned worker through a real armed desktop gateway: first
  demand spawns the worker inside its containment; an authenticated,
  receipt-owned administrative shutdown reaps the worker tree via the
  containment on the graceful stop, and the worker port frees before any force
  kill.

## Outcome

Real worker, run-owned provider, terminal, and authoring/projected/harness MCP
descendants are contained before work and reaped whole on both the graceful and
the forced/orphaned terminal paths, with no recursive process discovery. Gates:
`ruff check`/`format` clean, `ty check` clean. New file = 4 tests passed.
Desktop baseline `pytest desktop_tests -m "not service"
--ignore=test_dependency_closure.py` = 28 passed, 26 deselected. Closeout suite
`pytest api control worker providers utils` = 929 passed, 18 deselected.

## Notes

The external Claude/Codex provider binary is not installed in this environment,
so a real Python process launched through the genuine `spawn_acp_process` seam
stands in for it - the only mock permitted by the row, and only for the
unavailable CLI. The containment machinery itself (worker spawner, provider
spawner, terminal spawner, bounded terminate) is exercised with REAL child
processes throughout. The three MCP descendant types are modelled as the
provider stand-in's real children, which is faithful to production: a real
provider CLI launches its MCP servers as its own children, and the containment
reaps by job / process-group membership regardless of what the child runs. POSIX
containment is correct by construction but unexercised on this Windows host; the
Windows Job Object path is fully exercised here. With this Step, `W04.P11` is
complete: drain, token retention, worker/provider/terminal containment, bounded
discovery-free termination, and the integrated real-descendant proof all land.
