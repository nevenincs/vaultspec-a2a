---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S15'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Verify the document personas name the composed rag tools and native read tools against Kimi native read tool names and add a lane note only if the wording requires it (executor-service)

## Scope

- `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`

## Description

- Verify the researcher persona's grounding instructions (`mcp__vaultspec-rag__search_vault`/`search_codebase`/`get_code_file` + native Read/Grep/Glob) against Kimi's ACTUAL native read tool names, read from the installed kimi-cli 1.49.0 source.
- Decide whether a lane-conditional note is required, and record the judgment.

## Outcome

JUDGMENT: NO persona change required - the researcher persona is left unchanged.

Kimi's native read tools, source-verified from the installed package (`C:\Users\hello\AppData\Roaming\uv\tools\kimi-cli\Lib\site-packages\kimi_cli`): `ReadFile` (`tools/file/read.py:64` `name = "ReadFile"`), `Grep` (`tools/file/grep_local.py:386`), `Glob` (`tools/file/glob.py:56`); the tool-name dispatch confirms the same set (`tools/__init__.py:58/66/70` cases `ReadFile`/`Glob`/`Grep`). Comparison with the persona's named tools (`Read`, `Grep`, `Glob`): `Grep` and `Glob` are EXACT matches on both the Claude and Kimi lanes; the only divergence is Claude `Read` vs Kimi `ReadFile`.

The persona's wording does NOT require a lane note: `Grep`/`Glob` are exact on both lanes, and the persona's read instructions are intent-descriptive ("Read each relevant record in full", "Read it whole", "the native read tools") rather than a hard tool-invocation contract - a Kimi document agent maps "read the file" to its `ReadFile` tool naturally. Adding a Kimi-conditional "use ReadFile" note would (a) clutter a shared persona for a one-tool cosmetic delta the model already bridges, and (b) risk making the Claude lane (whose tool IS literally `Read`) less exact. The plan's criterion is "add a lane note only if the wording requires it"; it does not.

Grounding: Read the installed kimi-cli source directly (uv tool venv) for the authoritative tool names, and the accepted `2026-07-17-kimi-provider-adr` (read-only enforcement = exact-name auto-approve set at the permission-RPC handler). (rag not queryable for the installed-tool path; source Read is the authoritative method here.)

## Notes

RELAY TO EXECUTOR-CORE (P03.S10 enumeration - the exact-name enforcement point, not the persona): the read-only auto-approve allowlist for the Kimi lane MUST use Kimi's native read tool names `ReadFile`, `Grep`, `Glob` - specifically `ReadFile`, NOT Claude's `Read`. The persona is soft prompt guidance and is name-tolerant; the permission-RPC auto-approve set (ADR: exact-name, never blanket `--yolo`) is where the divergence is load-bearing and must be authoritative. Flagged so the P03 enumeration and my persona verdict do not diverge.

No code change for S15 (verification + recorded judgment). Gate: the researcher persona is unchanged and still parses (`role = researcher`, `terminal = false`).
