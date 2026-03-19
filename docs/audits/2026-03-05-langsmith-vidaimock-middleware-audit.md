# LangSmith + VidaiMock Middleware Audit (Cycle Log)

**Date**: 2026-03-05  
**Scope**: Docker middleware backend powering frontend integration (LangSmith + VidaiMock)  
**Status**: Active  
**Audit Mode**: Continuous, multi-cycle  
**Triage Scale**: Critical | Low  

---

## Cycle One — Tasks Logged

| ID | Triage | Task | Notes |
|----|--------|------|-------|
| C1-T01 | **Critical** | Replace legacy LangSmith env vars in code paths (remove `LANGCHAIN_*` reads/writes) and standardize on `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`. | Current telemetry module reads legacy vars; Docker passes canonical vars. Align to avoid misleading telemetry state and reduce maintenance. |
| C1-T02 | **Critical** | Update `lib/telemetry/instrumentation.py` to read canonical LangSmith vars first and remove legacy fallbacks once all call sites are updated. | Must match official docs and internal `.env` and docker-compose naming. |
| C1-T03 | **Critical** | Extend the core settings layer to explicitly handle LangSmith env vars (canonical names only) and consolidate any wrangling in a single authoritative settings source. | Ensures the settings library is the only source of truth; prevents scattered `os.environ` reads. |
| C1-T04 | **Low** | Update developer-facing docs and examples to remove `LANGCHAIN_*` references. | Cleanup for consistency; keep any historical references only when explicitly marked as legacy context. |

---

## Cycle Two — Tasks Logged

| ID | Triage | Task | Notes |
|----|--------|------|-------|
| C2-T01 | **Critical** | Remove legacy env variables from Docker and runtime configuration (`docker-compose.dev.yml`, `.env`, and any scripts) once code no longer depends on them. | Ensures runtime is fully canonical and reduces configuration drift. |
| C2-T02 | **Low** | Add a brief audit note in relevant ADRs or audit logs stating that LangSmith canonical variables are enforced and legacy variables are deprecated/removed. | Documentation alignment only; no functional impact. |

---

## References (Docs Used in Audit)

- LangSmith official environment variables: `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`  
- LangChain/LangGraph guidance on model and tracing configuration  
- VidaiMock official documentation and CLI usage  

---

## Cycle Three — Tasks Logged

| ID | Triage | Task | Notes |
|----|--------|------|-------|
| C3-T01 | **Critical** | Remove legacy `LANGCHAIN_*` references in telemetry implementation and tests once canonical LangSmith vars are the only supported path. | Documentation and telemetry logs must reflect canonical env vars only. |
| C3-T02 | **Critical** | Align audit references and operational guidance with canonical LangSmith vars per official docs. | LangSmith docs state `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` are best practice. |
| C3-T03 | **Low** | Update any remaining research notes that still present `LANGCHAIN_*` as instructions (keep historical references explicitly marked as legacy). | Reduce confusion for operators and maintainers. |

---

## Cycle Four — Tasks Logged

| ID | Triage | Task | Notes |
|----|--------|------|-------|
| C4-T01 | **Critical** | Verify and document removal plan for `LANGCHAIN_*` usage in telemetry/runtime code paths to ensure only canonical `LANGSMITH_*` vars remain. | Grounded in LangSmith docs: canonical env vars are `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`. |
| C4-T02 | **Critical** | Audit and list every remaining `LANGCHAIN_*` reference in `lib/` and tests; classify as removal vs. legacy historical context. | Ensure compliance with ADR guidance and canonical env vars. |
| C4-T03 | **Low** | Record any documentation that still presents `LANGCHAIN_*` as active instructions and mark them explicitly as legacy if retained. | Keep historical references only when clearly labeled. |

---

## Cycle Five — Tasks Logged (Deep Audit)

| ID | Triage | Task | Notes |
|----|--------|------|-------|
| C5-T01 | **Critical** | Validate `LANGSMITH_ENDPOINT` usage across runtime and docs against official requirements (must include `/v1` when set via env). | Official docs require `/v1` suffix for `LANGSMITH_ENDPOINT` env var in API usage. |
| C5-T02 | **Critical** | Audit and reconcile all LangSmith config guidance across ADRs, research notes, and runtime logging to ensure canonical `LANGSMITH_*` usage only. | Align with LangSmith docs: `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`. |
| C5-T03 | **Low** | Record any non-canonical LangSmith guidance as legacy-only with explicit labels, or retire it if not required. | Keeps historical context without encouraging legacy usage. |

---

## Cycle Six — Tasks Logged (Deep Audit)

| ID | Triage | Task | Notes |
|----|--------|------|-------|
| C6-T01 | **Critical** | Verify VidaiMock configuration and tape routing compliance with official VidaiMock docs (endpoints, streaming, config-dir behavior). | Ensure the mock server behavior aligns with documented OpenAI-compatible endpoints and streaming expectations. |
| C6-T02 | **Critical** | Audit LangGraph persistence usage to confirm AsyncSqliteSaver setup and lifecycle matches official LangGraph guidance for async checkpointers. | LangGraph docs emphasize async context manager usage and setup before graph execution. |
| C6-T03 | **Low** | Consolidate any VidaiMock or LangGraph persistence guidance in docs to avoid conflicting setup instructions. | Keep operational guidance consistent across ADRs and research notes. |

---

## Cycle Seven — Findings (Deep Audit)

1) **Critical** — VidaiMock healthcheck uses `/v1/models`, but official docs only demonstrate `/v1/chat/completions` and do not explicitly guarantee `/v1/models` as a readiness signal.  
2) **Critical** — VidaiMock `--config-dir` semantics are ambiguous in docs: default structure is `config/providers/`, but repo mounts `/app/tapes/providers/` and relies on `--config-dir /app/tapes` without explicit doc confirmation that this layout is supported.

---

## Cycle Eight — Findings (Deep Audit)

1) **Low** — VidaiMock documentation pages for custom providers/templates/chaos returned 404 during audit, creating gaps in authoritative guidance for tape schema and override behavior.  
2) **Low** — No explicit VidaiMock doc section found that defines expected directory layout when `--config-dir` is provided; this is an interpretation risk for ops and CI.  
3) **Critical** — Duplicate of Cycle Seven: `/v1/models` readiness endpoint not explicitly documented.  
4) **Critical** — Duplicate of Cycle Seven: `--config-dir` directory semantics not explicitly documented.

---

## Cycle Nine — Findings (Deep Audit)

1) **Critical** — `docker-compose.dev.yml` sets `LANGSMITH_ENDPOINT` to `https://api.smith.langchain.com` (no `/v1`), while official LangSmith docs state that the env var must include `/v1` (e.g., `https://api.smith.langchain.com/v1` or self‑hosted `/api/v1`).  
2) **Low** — Internal research guidance (`docs/research/2026-03-04-langsmith-env-variable-naming.md`) lists `LANGSMITH_ENDPOINT=https://api.smith.langchain.com` without `/v1`, which conflicts with current official docs and risks propagating a non‑compliant default.

---

## Cycle Ten — Findings (Deep Audit)

1) **Critical** — Worker auth config drift: ADR‑031 requires `VAULTSPEC_INTERNAL_TOKEN` for internal IPC in production, but the worker app initialization uses `settings.internal_token` and `settings.api_base_url` which are not defined in `lib/core/config.py`, indicating a configuration gap that can disable or bypass the intended auth mechanism.  
2) **Low** — The worker process uses a loopback‑only binding by default; this reduces exposure, but does not eliminate the need for the token as required by ADR‑031.

---

## Cycle Eleven — Findings (Deep Audit)

1) **Critical** — ADR‑031 specifies internal IPC endpoints at `/api/internal/*`, but the worker bridge posts to `/internal/events` and `/internal/heartbeat` (missing `/api` prefix). This is a contract drift and may bypass internal routing expectations.  
2) **Low** — ADR‑031 specifies heartbeat payload includes `uptime_seconds`, but the worker heartbeat currently sends `worker_id`, `active_threads`, and `timestamp` only.

---

## Cycle Twelve — Findings (Deep Audit)

1) **Critical** — ADR‑011 specifies REST routes without `/api` prefix (e.g., `/threads`, `/team/status`), but the implementation mounts REST under `/api` (`/api/threads`, `/api/team/status`). This is a published contract drift that can break frontend routing if it follows ADR‑011 literally.  
2) **Low** — Field naming is inconsistent across contract surfaces: REST uses `active_threads` (TeamStatusResponse), WebSocket `TeamStatusEvent` uses `active_thread_ids`, and `ConnectedEvent` uses `active_threads`. This increases frontend mapping complexity and should be normalized or explicitly documented in ADR‑011.

---

## Cycle Thirteen — Findings (Deep Audit)

1) **Critical** — Telemetry still reads legacy `LANGCHAIN_*` vars (`LANGCHAIN_TRACING_V2`, `LANGCHAIN_PROJECT`) and does not reference canonical `LANGSMITH_*` env vars. This conflicts with current LangSmith guidance that best practice is `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`, with `LANGCHAIN_*` treated as legacy aliases.  
   **Evidence:** `lib/telemetry/instrumentation.py` reads `LANGCHAIN_TRACING_V2` and `LANGCHAIN_PROJECT` only.  
   **Doc ground:** LangSmith env var guidance and legacy alias note (<https://docs.langchain.com/langsmith/trace-without-env-vars>, <https://docs.langchain.com/langsmith/observability-llm-tutorial>).

2) **Critical** — `docker-compose.dev.yml` sets `LANGSMITH_ENDPOINT` default to `https://api.smith.langchain.com` without `/v1`. LangSmith docs explicitly state the env var must include `/v1` (or `/api/v1` for self-hosted) when configured via `LANGSMITH_ENDPOINT`.  
   **Evidence:** `docker-compose.dev.yml` mock-seeder environment block.  
   **Doc ground:** LangSmith API endpoint requirement for `LANGSMITH_ENDPOINT` (<https://docs.langchain.com/langsmith/cicd-pipeline-example>, <https://docs.langchain.com/langsmith/self-host-usage>).

3) **Low (Verified/Aligned)** — Worker checkpointer lifecycle matches LangGraph guidance: uses `AsyncSqliteSaver.from_conn_string(...)` inside an async context manager and calls `await saver.setup()` before use.  
   **Evidence:** `lib/worker/app.py` uses `AsyncSqliteSaver.from_conn_string(...)` with `await checkpointer.setup()` in lifespan.  
   **Doc ground:** LangGraph checkpointer async context manager pattern (<https://docs.langchain.com/langsmith/custom-checkpointer>) and checkpointer library listing for SQLite (<https://docs.langchain.com/oss/python/langgraph/persistence>).

---

## Cycle Fourteen — Findings (Deep Audit)

1) **Critical** — Internal IPC endpoints are unauthenticated despite ADR‑031 requiring `VAULTSPEC_INTERNAL_TOKEN` in production. The gateway exposes `/internal/events` and `/internal/heartbeat` without any auth dependency, and the only auth module is a no‑op stub.  
   **Evidence:** `lib/api/internal.py` defines the `/internal/*` routes without auth; `lib/api/auth.py` explicitly states it is a no‑op stub.  
   **Doc ground (internal):** ADR‑031 mandates the bearer token for internal IPC.

2) **Critical** — Worker `/dispatch` endpoint accepts any request without auth, enabling local/CI processes to inject work or cancel threads. This violates the same ADR‑031 internal IPC token requirement.  
   **Evidence:** `lib/worker/app.py` defines `POST /dispatch` with no authentication checks or dependencies.  
   **Doc ground (internal):** ADR‑031 requires `VAULTSPEC_INTERNAL_TOKEN` for internal IPC in production.

---

## Notes

- This audit log is the authoritative task ledger for this middleware audit cycle.  
- Recurring findings are tagged as duplicates and not counted as new gaps unless evidence changes.  
- Tasks will be expanded with owners, links, and completion evidence in subsequent passes.
