---
tags:
  - '#audit'
  - '#worker-process-architecture'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:66c6faf3247e37d800870352789af3965ac9efb04d49f95347e2f6aa5de3ac06'
related:
  - "[[2026-03-04-worker-process-architecture-adr]]"
  - "[[2026-08-04-canonical-homes-adr]]"
  - "[[2026-07-19-codebase-health-adr]]"
---
# `worker-process-architecture` audit: `Internal HTTP body-limit remediation`

## Scope

Authorized by the user's explicit 2026-10-04 request to fix the repository scan finding observed at revision b973403. This is direct work within the accepted worker process topology, shared-mechanism ownership, and bounded transport constraints; no implementation plan or new costly decision is required. Review covers the current working-tree changes to gateway and worker body admission, dispatch and heartbeat validation, and their focused regression tests. Concurrent authoring, desktop, provider, and service changes are excluded.

The limiter moves from `src/vaultspec_a2a/api/body_limit.py` to `src/vaultspec_a2a/ipc/body_limit.py`. Both app factories install the same mechanism with explicit gateway or worker policies. POST, PUT, PATCH, and DELETE are bounded before parsing. The existing versioned cap, configured internal cap, and configured larger event-batch allowance remain distinct.

Semantic code discovery returned index_unverifiable; service status reported failed indexing jobs. Targeted source discovery and accepted-ADR listing supplied grounding instead.

## Findings

### internal-http-body-admission | low | Internal body consumers lacked a received-byte bound

Type: security / resource exhaustion. Status: fixed in the candidate. The gateway event and batch endpoints checked only advisory Content-Length, heartbeat had no byte check, and the worker had no body middleware. The worker's typed dispatch JSON is read before its bearer dependency, so its allocation path is reachable before authentication; gateway event and heartbeat parsing occurs after router authentication. The shared middleware now counts actual received bytes before copying each chunk and stops at the violating chunk, irrespective of absent, chunked, malformed, duplicate, negative, or understated declared lengths. It rejects oversized declared bodies without receiving them. Rejected requests cannot mutate heartbeat liveness or admit dispatch IDs. Dispatch identity/content and heartbeat thread-list fields have explicit bounds; internal byte and batch-multiplier configuration must be positive.

Evidence: `src/vaultspec_a2a/ipc/body_limit.py:44`, `src/vaultspec_a2a/api/app.py:928`, `src/vaultspec_a2a/worker/app.py:459`, `src/vaultspec_a2a/ipc/schemas.py:155`, `src/vaultspec_a2a/ipc/schemas.py:310`, `src/vaultspec_a2a/api/internal.py:514`, `src/vaultspec_a2a/control/infra_config.py:878`. The four missing-length regression cases were run against the original implementation and failed because receiving continued past the overflowing chunk. The fixed cases return 413; exact-limit event, batch, and heartbeat bodies still succeed. A batch may still exceed the single-event cap. Small worker bodies retain authentication and validation errors.

### generated-dispatch-budget | medium | Successor transcript can exceed the configured dispatch allowance

Type: correctness / producer-consumer capacity mismatch. Status: open follow-up. Owner: gateway run-admission and successor-context budgeting. `src/vaultspec_a2a/control/thread_service.py:250` permits transcript construction from complete bounded messages and `src/vaultspec_a2a/control/thread_service.py:266` adds that transcript, graph, metadata, and preamble to the dispatch. The wire schema permits 100 messages of 65,536 characters each; default transcript depth is 20. A valid collection can therefore exceed the existing 1 MiB internal HTTP allowance. Enforcing the intended receiver cap now exposes this previously unenforced mismatch. Keep the security bound; future admission must budget the complete serialized dispatch, including derived context and later authority fields, before committing a run, with a typed refusal or an explicitly decided bounded context policy. Never silently truncate accepted conversation state or raise the receiver cap to hide the mismatch.

### generated-dispatch-budget-review | medium | Independent review reproduced the successor envelope mismatch

Type: correctness / contract regression. Status: open, queued with generated-dispatch-budget; this entry adds confirmation rather than a second task. A fresh read-only reviewer independently constructed a valid DispatchRequest with 20 full 65,536-character seed messages and serialized it using httpx. The body was 1,311,857 bytes before ingest graph-definition overhead, and the real worker factory returned 413 at the configured 1,048,576-byte cap. Producer tracing confirms that successor ingest includes the same transcript and additionally includes graph and authority data: `src/vaultspec_a2a/domain_config.py:224`, `src/vaultspec_a2a/database/checkpoints.py:46`, `src/vaultspec_a2a/control/thread_service.py:250`, `src/vaultspec_a2a/control/thread_service.py:387`, `src/vaultspec_a2a/api/routes/_gateway_run_start.py:405`, `src/vaultspec_a2a/control/dispatch.py:205`. Receiver enforcement is the requested security invariant; sender/admission budgeting remains a separate follow-up rather than weakening that cap.

The reviewer found no surviving received-byte bypass and no other confirmed candidate defect. Review classification is PASS for the bounded-body remediation, with this medium compatibility follow-up retained. Required validation is summarized below.

## Recommendations

Align durable run admission and complete serialized successor dispatch budgeting in follow-up work. If context selection or truncation semantics must change, assess the accepted run-continuation decision before choosing that policy.

## Verification

Outcome: fixed. Independent review found no surviving received-byte bypass. The medium generated-dispatch-budget finding remains open in this queue; no critical or high finding was returned.

Final validation used the isolated `fix/internal-http-body-limit` branch at base cefdadfd, with only this remediation's source, tests, audit, and feature-index changes. It reused the locked tooling environment from the main worktree with UV_PROJECT_ENVIRONMENT and set PYTHONPATH to the isolated src tree for tests. Concurrent workspace/ACP edits in shared infra_config.py and worker/app.py were excluded from the isolated candidate.

- `uv run --no-sync ruff check` and `uv run --no-sync ruff format --check` over api/app.py, api/internal.py, worker/app.py, ipc/body_limit.py, ipc/schemas.py, control/infra_config.py, and api/tests/test_http_body_limits.py: pass.
- `uv run --no-sync ty check` and `uv run --no-sync basedpyright` over those seven files: pass, zero errors/warnings/notes.
- `uv run --no-sync python -m dev.quality.types` in the isolated worktree: pass. An earlier shared-worktree run failed on concurrent authoring changes; its diagnostic in the new lifespan helper was corrected and the affected checks rerun successfully.
- `uv run --no-sync python -m vaultspec_a2a.testing.runner -- src/vaultspec_a2a/api/tests/test_http_body_limits.py src/vaultspec_a2a/api/tests/test_app.py src/vaultspec_a2a/api/tests/test_internal.py src/vaultspec_a2a/api/tests/test_internal_auth.py src/vaultspec_a2a/api/tests/test_internal_worker_ipc.py src/vaultspec_a2a/worker/tests/test_app.py src/vaultspec_a2a/worker/tests/test_ipc.py src/vaultspec_a2a/worker/tests/test_ipc_batch_bounds.py src/vaultspec_a2a/ipc/tests src/vaultspec_a2a/worker/tests/test_executor.py src/vaultspec_a2a/control/tests/test_dispatch_refusal_classification.py src/vaultspec_a2a/control/tests/test_thread_service_tokens.py -q --no-showlocals`: pass, 244 tests, including 49 dedicated regression cases.
- `uv run --no-sync vaultspec-core vault check all`, `uv run --no-sync python dev/vault_annotations_gate.py`, and `git diff --check` in the isolated worktree: pass.

The original four routes now reject oversized missing-length or chunked bodies at the first overflowing chunk, before JSON/model allocation and before liveness or dispatch mutation. Misleading lengths and UTF-8 inputs cannot defeat the byte cap. Exact-cap gateway bodies, larger permitted event batches, small-body authentication/validation, real executor behavior, and dispatch refusal classification retain passing evidence. This validation exercises real ASGI applications; no live deployment or external scan-state write was requested.

Commit hooks: Ruff lint, Ruff formatting, whole-tree Ty, Markdown lint, Vault Doctor, Vault annotation gate, and Vaultspec commit gate all passed. Unrelated file-type hooks had no applicable files. The patch is retained on `fix/internal-http-body-limit`; the shared main worktree retains its local fix alongside concurrent work.
