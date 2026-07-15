---
tags:
  - '#research'
  - '#model-profiles'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-15-a2a-edge-conformance-plan]]"
  - "[[2026-02-27-team-composition-topology-adr]]"
---

# `model-profiles` research: `model profiles and team eligibility: triage of the dashboard discovery handover`

Question: the dashboard handover (`Y:/code/vaultspec-dashboard-worktrees/main/tmp/tmp3.md`, 2026-07-15) requires product-safe team discovery, backend-served run eligibility, and a selectable model profile for heterogeneous teams - and names as prerequisite the revision of the existing decision that per-request model overrides are unsupported with team presets. Conclusion of the evidence: the resolution chain and workspace-over-bundled discovery idioms already exist to build on; provider readiness ahead of instantiation does not exist at all and is the one genuinely new runtime capability; the override prohibition can survive in spirit (no caller-authored model maps) while named profiles become the sanctioned selector.

## Findings

### The precedence chain is real, tested, and has exactly one insertion point

ADR-013 §2.3 precedence (per-worker override > agent TOML > team defaults, with `provider_fallback` tried in order) is implemented verbatim at `src/vaultspec_a2a/graph/compiler.py:159-192` and consumed at `:121-157`. A selected profile is naturally a fourth, top layer: per-role assignments that win over all three when present, with absent roles falling through unchanged - which makes `team-defaults` the empty overlay for free.

### Provider readiness does not exist ahead of instantiation

Availability is discovered only by try/except around `factory.create` per provider at compile time (`compiler.py:129-152`); nothing can answer "is claude ready?" without spawning. A readiness probe (credential presence per provider from settings, command/binary resolvability via the existing `_classify_*` resolvers, engine reachability for authoring) is new work and the load-bearing dependency for truthful eligibility. No secrets leave the probe - it reports booleans and safe reasons only.

### Discovery idioms already exist; the truthful record is landing in plan-2

Workspace-over-bundled resolution is the documented config discovery order (`team/team_config.py:1-38`). The truthful presets-list record (loadable status, unavailable_reason, roles, capability, mock marking, workspace context) is in flight as `2026-07-15-a2a-edge-conformance-plan` P01.S02; the handover's discovery shape is a superset adding origin, profiles, per-role effective assignments, and eligibility - so this feature extends that record rather than forking it.

### The prior decision narrows rather than reverses

The team-composition record (`2026-02-27-team-composition-topology-adr`, §2.3 tables) and the dispatch-overrides audit finding hold that callers cannot pass per-request model overrides with a preset. The handover's own baseline (named, backend-defined profiles; arbitrary caller maps stay prohibited) preserves that decision's rationale - config-owned model policy - while adding a declared, validated selection surface. Amendment, not reversal.

### Freeze-and-persist has existing carriers

Run metadata already persists thread-scoped launch context (team_preset on the thread row; `run-start` hardening in plan-2 S01 added client idempotency). The frozen effective assignment is one more run-metadata record plus a digest; restart recovery reads it instead of re-resolving - satisfying the handover's no-silent-re-resolution and never-silent-fallback rules.

Not investigated: per-provider capacity/quota signals (readiness here is presence/resolvability, not rate-limit headroom); profile-level cost estimation.

## Sources

- `Y:/code/vaultspec-dashboard-worktrees/main/tmp/tmp3.md`
- `src/vaultspec_a2a/graph/compiler.py:121-192`
- `src/vaultspec_a2a/team/team_config.py:1-38`
- `src/vaultspec_a2a/providers/factory.py:247-279` (supported-provider guard; no readiness probe)
- `2026-02-27-team-composition-topology-adr` §2.3 (precedence tables, lines 94-201)
- `2026-07-15-a2a-edge-conformance-plan` P01.S01-S02 (landed run-start hardening, in-flight truthful presets-list)
