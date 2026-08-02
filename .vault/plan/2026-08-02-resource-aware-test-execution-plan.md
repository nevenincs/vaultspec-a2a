---
tags:
  - '#plan'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_hash: 'sha256:5bccaa51260aa0b1555d0fd0c867647d1ec6e6318e1cb7450ed07c0abdc28fa9'
tier: L1
related:
  - '[[2026-07-15-dev-process-registry-adr]]'
  - '[[2026-08-02-resource-aware-test-execution-adr]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #plan) and one feature tag.
     Replace resource-aware-test-execution with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     tier is mandatory for new plans. Allowed: L1, L2, L3, L4.
     L1 = Steps only. L2 = Phases above Steps. L3 = Waves above
     Phases above Steps. L4 = Epic above Waves above Phases above
     Steps; PM association required. Pre-existing plans without this
     field default to L2.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'. The related field
     carries the AUTHORIZING documents (ADR, research, reference, prior
     plan) for every Step in this plan; Steps inherit this chain;
     per-row reference footers do not exist.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->


<!-- HIERARCHY AND TIERS:
     Epic > Wave > Phase > Step. Step is the canonical leaf-row
     noun. Execution Record artifact: <Step Record>.
     Tier is declared in frontmatter as tier: L1/L2/L3/L4
     (mandatory for new plans; pre-existing plans without the
     field default to L2 and the writer adds the field on first
     edit). The tier selects containers:
       L1 = Steps only.
       L2 = Phases above Steps.
       L3 = Waves above Phases above Steps.
       L4 = Epic above Waves above Phases above Steps; MUST declare
            a project-management association in the Epic intent
            block prose.
     Selection is by complexity criteria, not container counting.
     Writer never invents containers to qualify a tier. -->

<!-- IDENTIFIERS AND ROW CONTRACT:
     S##, P##, W## are flat, per-document, append-only, immutable.
     Promotion adds containers without renumbering. Gaps are not
     reused.
     Display paths are computed from current grouping:
       Step path:    L1 S##   L2 P##.S##   L3/L4 W##.P##.S##
       Phase heading:        L2 P##       L3/L4 W##.P##
       Wave heading:                      L3/L4 W##
     Row format:
       - [ ] `<display-path>` - imperative-verb action; `path/to/file`.
     Two-state checkboxes only ([ ] open, [x] closed). No per-row
     reference footers; wiki-links and markdown links are forbidden
     in plan body. Authorizing documents go in the plan's `related:`
     frontmatter once.
     ASCII spaced hyphens everywhere; em-dash (U+2014) and en-dash
     (U+2013) are forbidden. Step rows within a Phase are
     contiguous. -->

<!-- NO COMPRESSION:
     N self-similar actions = N rows. Never collapse into "for each
     X, do Y" / "across all callers, do Z" / "in every module,
     replace W". The rule applies at every tier including L1. -->

<!-- VAULTSPEC-CORE VAULT PLAN CLI:
     The `vaultspec-core vault plan` CLI is the canonical surface for
     structural manipulation of this plan document. Writers and
     executors MUST use `vaultspec-core vault plan step add/insert/move/
     remove/check/uncheck/toggle/edit`,
     `vaultspec-core vault plan phase add/move/remove/edit`,
     `vaultspec-core vault plan wave add/move/remove/edit`,
     `vaultspec-core vault plan epic intent`, and
     `vaultspec-core vault plan tier promote/demote` for every
     identifier-affecting change rather than hand-editing the row
     grammar. Hand edits are tolerated by the parser but flagged by
     `vaultspec-core vault plan check`; canonical-identifier preservation is
     guaranteed only when the CLI performs the mutation. Run
     `vaultspec-core vault plan --help` for the full subcommand
     surface. -->

# `resource-aware-test-execution` plan

Deliver the two-layer test execution framework decided in
`2026-08-02-resource-aware-test-execution-adr`: machine-global resource leases
as the correctness layer, declaration-derived `loadgroup` distribution as the
throughput layer, registry-backed service resolution, and progress-based
deadlines in place of one arbitrary global timeout.

## Description

Executes `2026-08-02-resource-aware-test-execution-adr`. A new `testing`
subpackage carries the resource vocabulary, the lease primitive (same `O_EXCL`
plus pid-liveness discipline as the dev-process registry), progress deadlines
judged on owner pid and heartbeat together, and endpoint resolution from the
lifecycle registry. A pytest plugin wires declarations to `xdist_group`
computation, guards against blind distribution modes, derives per-item timeout
backstops, and exposes acquisition fixtures that refuse undeclared use. The
hardcoded gateway default in the pw7 acceptance harness is replaced by registry
resolution, closing the audited harness-registry gap.

## Steps

- [ ] `S01` - Add the pytest-xdist dev dependency under the locked profile; `pyproject.toml`.
- [ ] `S02` - Implement the resource catalog and marker vocabulary; `src/vaultspec_a2a/testing/resources.py`.
- [ ] `S03` - Implement machine-global exclusive and shared resource leases; `src/vaultspec_a2a/testing/leases.py`.
- [ ] `S04` - Implement progress deadlines with pid-and-heartbeat liveness watch; `src/vaultspec_a2a/testing/progress.py`.
- [ ] `S05` - Implement registry-backed gateway and worker endpoint resolution; `src/vaultspec_a2a/testing/endpoints.py`.
- [ ] `S06` - Implement the scheduling plugin with group computation, dist-mode guard, backstop derivation, and acquisition fixtures; `src/vaultspec_a2a/testing/plugin.py`.
- [ ] `S07` - Wire the plugin into the root conftest and register the resource marker; `src/vaultspec_a2a/conftest.py`.
- [ ] `S08` - Replace the hardcoded gateway default with registry resolution in the pw7 harness; `src/vaultspec_a2a/service_tests/test_pw7_acceptance.py`.
- [ ] `S09` - Prove lease serialization and declaration-derived concurrency with real subprocess runs; `src/vaultspec_a2a/testing/tests/`.
- [ ] `S10` - Run whole-tree gates, classify findings, and close the rolling audit for this feature; `pyproject.toml`.

<!-- The plan's tier (declared in frontmatter as `tier: L1`, `L2`, `L3`, or
`L4`) determines the structure under this section:

- `L1`: a flat list of Step rows (no Phase, Wave, or Epic).
- `L2`: one or more `### Phase` blocks each containing Step rows.
- `L3`: one or more `## Wave` blocks each containing Phase blocks.
- `L4`: a `## Epic intent` block, followed by Wave blocks. -->

<!-- Replace this scaffold with the tier-appropriate structure for your plan.
Format examples for each block type are embedded below as commented
templates. -->

<!-- IMPORTANT: This document must be updated between execution runs to
     track progress. -->

<!-- PHASE BLOCK FORMAT (L2, L3, L4):
     ### Phase `P02` - rewrite the writer-agent contract

     One sentence stating what this Phase delivers.

     - [ ] `P02.S01` - imperative-verb action; `path/to/file`.
     - [ ] `P02.S02` - imperative-verb action; `path/to/file`.

     At L3/L4 the Phase heading uses the ancestor-aware path
     (### Phase `W01.P02` - ...). The intent sentence is mandatory. -->

<!-- WAVE BLOCK FORMAT (L3, L4):
     ## Wave `W01` - language-only convention rollout

     One paragraph stating what this Wave delivers, which downstream
     Wave depends on it, and which authorizing documents back it.

     ### Phase `W01.P01` - ...
     ### Phase `W01.P02` - ...

     The Wave intent paragraph is mandatory. -->

<!-- EPIC INTENT BLOCK FORMAT (L4 only):
     ## Epic intent

     One paragraph stating the strategic goal, the external project-
     management association (milestone name, project board identifier,
     roadmap entry), the timeline horizon, and the teams or agents
     involved.

     ## Wave `W01` - ...
     ## Wave `W02` - ...

     The ## Epic intent block is mandatory at L4 and absent at L1, L2,
     L3. The plan title (the level-one # heading at the top of the
     document) is the Epic title; no separate Epic heading is emitted. -->

## Parallelization

Steps are sequenced: the catalog and lease primitives precede the plugin, the
plugin precedes the harness migration, and the subprocess evidence run precedes
the closing gates. A single executor lands the whole plan.

## Verification

- A real subprocess run shows two tests declaring the same exclusive resource
  never overlap in time, while two tests with disjoint declarations do overlap
  under a two-worker `loadgroup` run.
- Lease exclusion holds without any scheduler: two concurrent contending
  processes serialize at acquisition time.
- A progress deadline trips on a killed owner pid and on a frozen heartbeat,
  and does not trip on a slow-but-progressing consumer.
- The pw7 harness resolves a gateway allocated off the band default via the
  registry, with no hardcoded `18100` fallback remaining.
- `-n` with a dist mode other than `loadgroup` aborts with a usage error.
- Whole-tree ruff, ty, and the full default pytest suite pass; findings are
  classified in the rolling audit.
