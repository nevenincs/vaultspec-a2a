---
tags:
  - '#audit'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - '[[2026-07-14-a2a-edge-conformance-plan]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
---

# `a2a-edge-conformance` audit: `dead code campaign`

## Scope

Systematic dead-code sweep of the repository following the headless pivot (the
`src/ui/` removal and the Google-A2A stub removal completed in earlier waves).
Targets were residual UI-era build wiring, orphaned middleware, stale MCP and
tooling configuration, unreferenced pytest collection roots, and superseded team
presets. Each candidate was ruled either DELETE (proven dead) or KEEP (proven
live, with rationale); negatives are recorded here so the sweep is auditable
rather than silently selective. Execution ran across parallel agent sessions
under team-lead deconfliction on a shared worktree, so two multi-writer commit
races are recorded as process findings.

## Findings

### dockerfile-ui-stage | low | prod image carried a broken frontend-build stage

The production Dockerfile under `service/docker/prod.Dockerfile` still declared a
frontend-build stage and copied an SPA dist that no longer exists. Replaced with a
minimal node-deps stage that runs `npm ci --omit=dev` for the
`@zed-industries/claude-agent-acp` dependency only; removed the SPA dist COPY and
the `VAULTSPEC_UI_BUILD_DIR` env. Landed in `5d41f94`.

### compose-ui-wiring | low | dev/prod compose still wired a frontend service

`service/docker-compose.dev.yml`, `service/docker/dev.Dockerfile`, and
`service/docker-compose.prod.yml` carried a frontend service, a node-base build
target, and stale SPA comments. All removed. Landed in `5d41f94`.

### cachecontrol-middleware | low | orphaned middleware husk after UI removal

`src/vaultspec_a2a/api/middleware.py` contained only `CacheControlMiddleware`,
which existed solely to serve SPA cache headers. Module deleted; its import and
registration were stripped from `src/vaultspec_a2a/api/app.py`, which now yields
17 headless routes. Landed in `5d41f94`.

### harness-ui-env | low | leftover UI build-dir env in the test harness

The `VAULTSPEC_UI_BUILD_DIR` reference in the test harness was removed. Landed in
`ccc0655` (scout-sonnet).

### pytest-norecursedirs-ui | low | stale "ui" pytest collection root

The `norecursedirs` entry for `ui` in `pyproject.toml` pointed at a collection
root that no longer exists; the `ui` entry was dropped and `node_modules` kept.
Landed in `5d41f94`.

### gemini-md-mirror | low | UI-era guidance mirrored in GEMINI.md

`GEMINI.md` mirrored the UI-era tool-chain and a check-generated-first note; both
were rewritten to the headless reality. Landed in `ccc0655` (scout-sonnet).

### gemini-settings-mcp | low | frontend MCP servers in local gemini settings

`.gemini/settings.json` still registered the figma, shadcn-ui, chrome-devtools,
and playwright MCP servers; these were removed and only context7 retained. NOTE:
`.gemini` is a gitignored local config, not a vaultspec-source-managed file, so
this change is local and uncommitted by design (no commit disposition).

### eslint-residue | low | eslint config confirmed absent (negative)

Checked for residual eslint configuration; none present. No action required.

### torch-dependency | low | torch ruled live, not dead (negative)

`torch` was evaluated as a possible dead dependency and ruled KEEP by team-lead;
it is a live dependency, not dead code. No action taken.

### preset-continuous-audit | low | superseded vaultspec-continuous-audit preset

The `vaultspec-continuous-audit` team preset TOML and its mention in the
`start_thread` tool docstring were removed. The TOML deletion landed in `5fbf2dd`
(swept into a P05.S12 commit under a multi-writer stage race; the file deletion is
correct and intended, but the commit title does not name the preset removal). The
paired docstring edit landed separately in `ce873e4`.

### justfile-ui-reference | low | UI-era reference in the Justfile

A UI-era reference in the `Justfile` was removed. Landed in `ccc0655`
(scout-sonnet).

### orchestrator-db-tracked | low | runtime database tracked in git

`data/orchestrator.db`, a runtime artifact, was tracked in git; it was removed
from the index and left gitignored. Landed in `ccc0655` (scout-sonnet).

### race-artifact-a542dbc | medium | duplicate-title commit from a shared-index race

Commit `a542dbc` carries a title identical to `796ee7a`
("production DocumentProposalSubmitter for phase gates") — a concurrent-commit
race artifact on the shared git index in which a co-resident staged change was
swept in under a superseded, duplicated title. The content is correct and
intended; only the title is mismatched.

### race-artifact-5fbf2dd | medium | preset deletion swept into an unrelated commit

Commit `5fbf2dd` ("live submitter proof", P05.S12) swept a co-resident staged
preset-TOML deletion into an unrelated authoring commit under a title that does
not name the deletion. Content correct and intended. The owning agent has since
adopted strict pathspec commits (`git commit -- <files>`) to prevent recurrence.

### sweep-negatives | low | packages swept clean with no dead code

The `workspace`, `ipc`, and `protocols/mcp` tool modules and the remaining
`team/presets` beyond the ruled preset deletions were swept and found clean; no
dead code was present in these areas.

### coder-preset-retirement | low | multi-role coder presets retired, topology coverage preserved

The three multi-role coding presets were retired as mission-superseded by the
headless pivot: `vaultspec-iterative-coder`, `vaultspec-structured-coder`, and
`vaultspec-adaptive-coder`. Their compiler topologies stay live under dashboard
contract D7e (preserved core) and D5 (topology choice remains ours), so per the
adopted OPTION A ruling the topology-behavior tests were repointed to
inline-constructed TeamConfigs (real models, real `compile_team_graph`, no
mocks); only the preset-only assertion tests were deleted. Incidental
"valid preset" fixtures across the executor, endpoint, discovery, and server
tests were repointed to the retained `vaultspec-solo-coder`. The MCP
`start_thread` no-arg default was repointed from adaptive to solo-coder before
deletion and proven end-to-end against the real in-process app. Ledger evidence
for the future keep-or-remove-topologies decision: each affected topology still
retains a bundled MOCK-preset that instantiates it in addition to the new inline
fixtures, so none is inline-test-only — `pipeline_loop` via `mock-autonomous`,
`star` via `mock-supervisor-human-in-loop`, and multi-node `pipeline` via
`mock-success-multi`.

### solo-coder-retained | low | solo-coder retained as the S20 re-arm vehicle

`vaultspec-solo-coder` is deliberately retained (alongside the non-coding
`vaultspec-adr-research`) as the sole single-role coding preset and is the
default. Watch note: it is the re-arm vehicle for the S20 solo-coder
propose-to-submit proof, which remains the standing acceptance path for the
authoring-run criterion; retiring or renaming it would break that proof.

## Recommendations

Adopt a serialized-commit or isolated-worktree model for multi-writer campaigns
on a shared git index. Both race artifacts above stem from non-pathspec
`git commit` sweeping co-resident staged changes; strict `git commit -- <paths>`
or per-agent worktrees prevents the class entirely.

The retirement of the multi-role coding presets (iterative, structured, adaptive)
left the `star`, `pipeline_loop`, and multi-node `pipeline` compiler topologies
without a bundled coder preset, while the compiler still supports them. Under the
adopted OPTION A ruling their topology-behavior coverage was preserved via inline
fixtures rather than dropped. Whether to eventually remove those topologies as
now-dead code is a contract-adjacent architecture decision (they are named
preserved core by dashboard contract D7e), deliberately left to the architect
successor ledger and not decided here; the mock-preset-plus-inline coverage noted
above is the evidence for that future decision.

Upstream tooling gap: `vault add audit` offers no topic-infix flag, so a second
same-day audit for one feature collides on filename and requires a
park-scaffold-rename workaround (tracked as vaultspec-core issue 205). A topic
option on the audit scaffold verb would remove the workaround.
