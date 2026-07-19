---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S18'
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
     The S18 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Add the manifest-declared desktop gateway invocation without changing Compose or foreground serve defaults and ## Scope

- `src/vaultspec_a2a/cli/main.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the manifest-declared desktop gateway invocation without changing Compose or foreground serve defaults

## Scope

- `src/vaultspec_a2a/cli/main.py`

## Description

- Add a `desktop-serve` subcommand under the existing operator CLI group, taking
  explicit `--app-home` and `--capsule-root` (plus optional `--host`/`--port`).
- Factor the launch assembly into a helper that resolves and fail-closed
  validates the desktop profile, materialises the mutable-state directories, and
  returns the armed environment plus the re-exec argv for the existing `serve`
  path.
- Arm the profile by setting the application-home and capsule-assets environment
  variables and re-execing `serve` in a freshly built interpreter, so the gateway
  boots through the one existing serve code path with desktop settings in force
  and the same launcher process identity.
- Reject an invalid or missing application home or an incomplete capsule
  fail-loud as an actionable CLI error before any boot.
- Cover the arming plan through its real seam (a capsule built from the provider
  factory path authorities, arming a real Settings) and drive the CLI command as
  a real child process for the rejection paths.

## Outcome

The dashboard-owned desktop gateway now has an explicit, manifest-conformant
launch: `vaultspec-a2a desktop-serve --app-home ... --capsule-root ...`. It seats
every mutable path under the explicit application home, binds the capsule assets
root, and starts the gateway through the unchanged `serve` path — no second boot
code path and no new run-control lifecycle verb. Plain `serve` and Compose
invocations are untouched. An invalid application home or a capsule missing its
bundled runtime assets fails loud with an actionable message before the gateway
starts.

## Notes

- Manifest reconciliation: the component manifest declares the gateway entry point
  reference as the `vaultspec-a2a` console script bound to the CLI `main`
  callable. The added command is a subcommand of that same callable, so the
  invocation resolves through the declared entry point exactly; the manifest does
  not declare subcommand arguments, so no divergence exists to reconcile.
- Binding mechanism: the gateway reads the process-global settings built at import
  time, so arming a profile after import requires the launch environment to be set
  before the settings are constructed. The command therefore sets the arming
  environment and re-execs the existing `serve`, which rebuilds settings from the
  armed environment. Re-exec preserves the launcher's process identity on POSIX;
  bounded process containment for the desktop tree is later-Wave work and is not
  claimed here.
