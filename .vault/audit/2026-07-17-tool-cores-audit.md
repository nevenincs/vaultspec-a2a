---
tags:
  - '#audit'
  - '#tool-cores'
date: '2026-07-17'
modified: '2026-07-17'
related:
  - "[[2026-07-17-tool-cores-adr]]"
  - "[[2026-07-17-tool-cores-plan]]"
  - "[[2026-07-17-tool-cores-dedup-audit]]"
---

# `tool-cores` audit: `S24 holistic safety and intent gate`

## Scope

The mandatory P05.S24 review gate over ALL landed tool-cores changes on main
(commit range `e50b88e..8b83f77`, tool-cores commits): P01-P05 implementation,
the P04 credential-cleanup fix, the codexwire harness-wiring defect fix, both
provider config-home modules, the registry/compose seam, the worker composition
site, presets and personas, and the exec/audit records — verified against
current file state on main, not only the per-branch diffs previously PASSed.
Reviewed by the team's dedicated code-review persona; verdict returned
2026-07-17 and persisted here verbatim in substance.

## Findings

**STATUS: PASS** — with the usage-gated live re-arms (`P01.S05`/`P03.S16`
Claude ~2026-07-20, `P04.S20`/`P04.S21` Codex ~2026-07-23) as honestly
recorded opens, and `P05.S25` reconciliation owed after this gate. No CRITICAL
or HIGH findings.

### Safety — read-only boundary, credential hygiene, isolation (clean)

- No write verb is composable on either lane: the registry holds exactly one
  entry (`vaultspec-rag`, `read_only: True`, three read tools); the
  write-capable vaultspec-core MCP and the rag `reindex_*` verbs are omitted
  by construction. The `_require_read_only` trust-root guard fires on BOTH
  transports (`src/vaultspec_a2a/providers/_acp_mcp.py:137` Claude home,
  `:179` Codex specs) so registry drift fails loud. Codex `enabled_tools` is
  an exact read-tool allowlist.
- The `.vault` write-deny is untouched; every live proof asserts zero
  agent-origin document-dir writes.
- Credential hygiene: the Claude isolated home is ZERO-credential (only
  `.claude.json`; auth rides env); the Codex home copies file-based
  `auth.json` owner-only (0o700 dir, 0o600 file) with single-turn lifetime,
  and the HIGH-1 fix places the home build INSIDE the streaming try
  (`src/vaultspec_a2a/providers/codex_chat_model.py:366`) with cleanup in the
  finally (`:429`) plus builder self-clean — every catchable failure reclaims
  the credential copy; only bounded, owner-only, prefix-tagged SIGKILL residue
  remains, honestly recorded.
- Isolation: both lanes redirect to a worker-owned config dir
  (`CLAUDE_CONFIG_DIR` / `CODEX_HOME`) carrying exactly the declared read-only
  servers; ambient operator MCP suppressed; no leak-back; cleanup on both
  paths.

### Intent — ADR decisions to landed code (no drift)

Every ADR decision has landed code or an honest open: the native read floor;
the mandatory adapter migration (deprecated pin retired) with regression
verification and the S20 re-probe; the ambient-suppression home built
regardless of the re-probe; the allowlist union closing the attach-combined
gap; preset opt-in and persona truth; the surfacing contingency correctly
triggered on the NOT-SURFACED verdict and live-verified SURFACES; the Codex
leg over the same registry; the vaultspec-core MCP correctly omitted. The
three unplanned commits each trace to an ADR-sanctioned path: the Docker
cross-libc fix serves the mandated migration, the harness-provisioning ADR
amendment is the ADR's own conditional clause firing, and the codexwire fix
completes the Codex leg after `P04.S21` discovered the production threading
was structurally dead (the direct-field tests had masked it — the masking
lesson is recorded in the `P04.S18` exec record).

### Completeness — opens are honest

Nineteen implementation and hygiene steps closed on reviewer-PASSed landed
evidence. The six opens at gate time were all honestly gated, none reported
as passing: `P01.S05` + `P03.S16` armed as parameter swaps of the green Z.ai
harness, blocked on the Claude weekly usage window; `P04.S20` + `P04.S21`
blocked on the Codex usage window (the wiring fix that must precede `S21` is
landed), each with a one-command re-arm; `S24` is this gate; `S25` follows.

### Evidence chain (spot-checked)

`P02.S09` NOT SURFACED is dispositive with a positive control; `P03.S14`
SURFACES is corroborated by the live `P03.S17` green (run `pw7-1784282060`)
whose server-side rag-daemon `POST /search` access-log evidence (400 then 200,
`service.search event=completed`, in-window) cannot be fabricated by native
tools; zero document writes across proofs.

### Residual unknown (correctly open)

Whether Codex ADMITS an MCP call at runtime under `approval_policy: "never"` +
`sandbox: "read-only"` + per-tool `approval_mode: "auto"` (the undocumented
axis composition) is held open under `P04.S21`, not asserted.

## Recommendations

Proceed to `P05.S25` reconciliation; execute the four usage-gated proofs when
the provider windows reset (Claude ~2026-07-20 08:00, Codex ~2026-07-23
06:15) using the one-command re-arms in their exec records; keep
`P01.S05`/`P03.S16`/`P04.S20`/`P04.S21` open until their green runs exist.
Carry forward the corroboration posture for semantic proofs (daemon-log
evidence recorded in exec records, disclosed as a non-test surface) and the
masking-gap lesson (never prove wiring by constructing states production
cannot reach).
