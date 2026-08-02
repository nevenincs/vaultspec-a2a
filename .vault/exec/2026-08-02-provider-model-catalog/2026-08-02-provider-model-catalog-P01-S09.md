---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:972677d8b9b9241899724958526bb82fdc7dedf0a57e92fd23ba983dc3c60181'
step_id: 'S09'
related:
  - "[[2026-08-02-provider-model-catalog-adr]]"
  - "[[2026-08-02-provider-model-catalog-plan]]"
---

# Freeze catalog provenance, exact model values, controls, fallbacks, execution modes, and schema version through compilation

## Scope

- `src/vaultspec_a2a/providers/model_profiles.py`
- `src/vaultspec_a2a/graph/compiler.py`

## Description

- Freeze exact provider model values, execution modes, native option values,
  ordered fallbacks, display provenance, and schema version in the durable run.
- Compile primary and fallback lanes exclusively from the frozen record.
- Apply exact Codex reasoning and service-tier values, Kimi alias and thinking
  effort, and ACP session configuration values at provider-native boundaries.
- Prefer modern frozen authority on restart while retaining legacy profiles only
  for runs that predate catalog selection.
- Disclose one validated digest-bearing frozen envelope through start, commit,
  replay, and status responses.
- Add real provider-factory, OS-pipe ACP, gateway race, replay, and restart
  isolation regressions.

## Outcome

Catalog-backed runs now carry a self-contained schema-v1 execution record from
admission through compilation, provider construction, restart, and public
disclosure. Restart does not query the live catalog and cannot silently adopt a
new model, execution backend, native control, or fallback order. Invalid modern
records fail only their owning thread and do not abort the reconciliation sweep.

Formal review classified four medium findings and all are resolved in the
assembled tree: missing replay disclosure, restart sweep isolation, mutation of
request identity by metadata enrichment, and generated-nickname masking of a
same-ID insert race.

## Notes

The S09 implementation is split across the assembled history because concurrent
shared-worktree commits `91765bfa`, `69333fad`, and `37db0011` captured the
compiler contract, one compiler regression, and the ACP exact-session runtime
while carrying unrelated work. Final verification therefore covers assembled
HEAD plus the remaining S09 payload; those commits must not be described as
standalone S09 commits.

Official Kimi CLI documentation confirms that model aliases use `-m`, no effort
flag is exposed, and model-scoped thinking effort is supplied through
`KIMI_MODEL_THINKING_EFFORT`. Installed Codex app-server schema confirms
`serviceTier` on `turn/start`.

The shared virtual environment reports stale installed package metadata
`0.2.0`. OpenAPI was generated and checked from an isolated locked editable
project environment, which reports the repository version `0.3.0`.
