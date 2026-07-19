---
tags:
  - '#research'
  - '#a2a-edge-conformance'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---
# `a2a-edge-conformance` research: `bounded active-run discovery`

The dashboard reload path needs a bounded way to rediscover durable non-terminal A2A runs before it can call the authoritative per-run snapshot and rebind the viewing transcript. The existing gateway has no collection read on `/v1/runs`; the evidence favors a capped active-run projection with optional workspace and feature filters, backed by the existing durable thread row and metadata, while excluding actor filtering until the run contract carries a stable non-secret actor identifier.

## Findings

### The existing lifecycle already defines the active complement

`ThreadStatus` persists submitted, running, input-required, cancelling, repair-needed, and reconciling states alongside terminal and archived states. `NON_ACTIVE_STATUSES` already defines completed, failed, cancelled, and archived as the complement, while `list_non_terminal_threads` queries every other durable row. Reusing that vocabulary avoids inventing a dashboard-only status interpretation. Sources: `src/vaultspec_a2a/thread/enums.py:10`, `src/vaultspec_a2a/database/thread_repository.py:128`.

### Workspace and feature selectors are durable; actor identity is not

Run start serializes `ThreadMetadata.workspace_root` and `feature_tag` into `threads.thread_metadata`, and the metadata model bounds provenance fields before persistence. Actor tokens instead exist only in the run-start bundle and are deliberately passed to worker-scoped runtime state without persistence. Workspace and feature can therefore filter discovery from durable data; an actor selector would either be fictional or require a separate dashboard contract field carrying a stable non-secret actor identifier. Sources: `src/vaultspec_a2a/context/metadata.py:44`, `src/vaultspec_a2a/control/thread_service.py:306`, `src/vaultspec_a2a/thread/actor_tokens.py:31`, `src/vaultspec_a2a/api/schemas/gateway.py:31`.

### A small projection preserves the D3/D5 boundary

The existing `run-status` response is the authoritative recovery snapshot and the SSE stream is explicitly droppable. Discovery only needs `run_id`, durable status, and feature tag so the dashboard can select a run and then fetch `run-status`; returning transcript content, topology, prompts, or actor credentials would duplicate authority and expand the engine whitelist unnecessarily. The response must retain the gateway's version discriminator and a hard result cap to remain safe under the engine pass-through envelope. Sources: `src/vaultspec_a2a/api/schemas/gateway.py:104`, `src/vaultspec_a2a/api/routes/gateway.py:386`, `.vault/adr/2026-07-14-a2a-edge-conformance-adr.md` R6 and R7.

### Collection-read alternatives narrow to filtered bounded discovery

Reusing internal `/api/threads` unchanged is rejected because it exposes broader internal lifecycle, repair, approval, title, preset, and branch fields and has no workspace filter. Returning only the newest active run is rejected because concurrent feature runs are valid and the dashboard must choose without guessing. A bounded list with `state=active`, optional exact workspace and feature filters, stable newest-first ordering, and a truncation signal preserves multiple-run truth while bounding response size.

## Sources

- `src/vaultspec_a2a/thread/enums.py:10`
- `src/vaultspec_a2a/database/thread_repository.py:128`
- `src/vaultspec_a2a/context/metadata.py:44`
- `src/vaultspec_a2a/control/thread_service.py:306`
- `src/vaultspec_a2a/thread/actor_tokens.py:31`
- `src/vaultspec_a2a/api/schemas/gateway.py:31`
- `src/vaultspec_a2a/api/schemas/gateway.py:104`
- `src/vaultspec_a2a/api/routes/gateway.py:386`
- `.vault/adr/2026-07-14-a2a-edge-conformance-adr.md`
