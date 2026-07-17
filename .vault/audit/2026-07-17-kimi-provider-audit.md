---
tags:
  - '#audit'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
related:
  - "[[2026-07-17-kimi-provider-adr]]"
  - "[[2026-07-17-kimi-provider-plan]]"
  - "[[2026-07-17-kimi-provider-dedup-audit]]"
---

# `kimi-provider` audit: `S20 holistic safety and intent gate`

## Scope

The mandatory P06.S20 review gate over ALL landed kimi-provider changes on
main (core merge `34c450e`, team merge `b32f384`, closures `cdb8869`, S19
sweep and correction `c9e7885`, residual amendment `ce79861`): enum, settings,
factory plumbing, per-backend `_meta` conditioning, the permission-RPC
read-only layer, per-run isolation, harness-wiring seam, team profile and
persona surface, and the vault record chain — verified against current main
file state, not only the previously PASSed per-branch diffs. Reviewed by the
team's dedicated code-review persona; verdict returned 2026-07-17 and
persisted here in substance.

## Findings

**STATUS: PASS** — with the key-gated live proofs (`P05.S16`/`P05.S17` floor
and semantic, `P05.S18` shape-(a) fallback) as honestly recorded opens armed
on `KIMI_API_KEY` arrival, and `P06.S21` reconciliation owed after this gate.
No CRITICAL or HIGH findings.

### Safety — read-only boundary end-to-end (clean)

- Exact-name default-deny at the only enforcement point Kimi offers: the
  autonomous kimi branch of the permission handler
  (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:259`) auto-approves
  exactly the stripped composed read names plus `ReadFile`/`Grep`/`Glob`
  (`:138`) and rejects everything else; supervised keeps the human prompt; no
  blanket `--yolo` anywhere. Eighteen permission tests drive the real handler
  including reject-by-default.
- The raw-name residual is explicitly recorded with its two-invariant
  coupling in the S10 and S12 exec records (`ce79861`): raw-name matching is
  the maximum precision Kimi's server-scopeless permission title allows, and
  it is load-bearing on the unconditional ambient-MCP isolation
  (`factory.py:318` inline `--config '{"mcpServers": {}}'`) plus the
  read-only registry trust-root. Accepted residual, not a defect.
- Credential hygiene: only the `KIMI_API_KEY` env passthrough (`SecretStr`,
  redaction-verified); the readiness probe checks presence without surfacing
  the value; no token values in any record.
- Zero delta to existing lanes: `acp_family` defaults `"claude"`
  (`src/vaultspec_a2a/providers/_acp_session.py:139` gates the allowedTools
  `_meta`), so Claude and Z.ai serialize byte-identically; regression suites
  green.

### Intent — ADR decisions to landed code (no drift)

Every ADR decision has landed code or an honest key-gated open: shape (b1)
native-ACP lane on `kimi acp`; backend-conditioned allowlist transport (no
shim); MCP delivery riding the EXISTING `with_mcp_servers` branch with no
third dispatch, proven through the real compose seam; permission-RPC
enforcement with `--yolo` rejected; per-run `--config` isolation; the
`kimi-cli==1.49.0` single-source pin with install hint and Git-Bash
prerequisite; the skip-loudly `[team.profiles.kimi]` overlay. `MOONSHOT`
correctly reserved, not built. The dated ADR Correction
(`KIMI_SHELL_PATH` to `KIMI_CLI_GIT_BASH_PATH`, installed source
`utils/environment.py:100`) is decision-neutral and appended per the
amendment convention. No drift beyond ADR scope.

### Completeness — opens are honest

Sixteen of twenty-one steps closed with evidence (S01-S15, S19). The five
opens at gate time: S16/S17/S18 armed on `KIMI_API_KEY` (mirroring the Z.ai
blocked-on-credentials-not-code precedent; S18 fires only if the primary
proof fails), S20 this gate, S21 reconciliation. Nothing in P05 is reported
as passing.

### Evidence chain (spot-checked)

The S01 grounding-and-dedup gate preceded all code; the S09 keyless handshake
live-spawns the installed `kimi acp` and reaps pre-session (re-run by the
reviewer: PASSED); the dual-grounding law holds across records (installed
kimi-cli path:line locators on every external claim); the ReadMediaFile
divergence-resolution note records the cross-executor enumeration catch that
tightened the floor to `{ReadFile, Grep, Glob}` before review.

## Recommendations

Proceed to `P06.S21` reconciliation. Execute S16-S18 when `KIMI_API_KEY`
arrives (one-command re-arms in their rows; keep them open until green runs
exist, with the established evidence standard: run id, narration or frames,
rag-daemon `/search` corroboration for the semantic proof, zero document-dir
writes). Carry forward: the raw-name-coupling residual should be re-examined
if the registry ever grows beyond the single rag server or if Kimi adds
server-scoped permission titles upstream.
