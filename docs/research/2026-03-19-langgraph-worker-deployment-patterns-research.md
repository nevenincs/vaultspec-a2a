# LangGraph Worker Deployment Patterns — Research Findings

**Date**: 2026-03-19
**Context**: Grounding for Phases 6-7 (env propagation, health checks)
**Source**: LangGraph docs (Context7), LangSmith deployment docs, Python subprocess docs

---

## LangGraph Platform Architecture

LangGraph uses a **two-tier container architecture**:

- **API Servers**: Handle client requests, create runs in durable queue,
  stream results. Do NOT execute agent code.
- **Queue Workers**: Listen to task queue, execute graph code, write
  checkpoints. Separate container pool, scales independently.

### Request Flow

```text
Client → API Server → Postgres (pending run) → Redis (notify)
  → Queue Worker (claim run, acquire lease) → Execute graph
  → Postgres (checkpoints) → Redis (stream events)
  → API Server (SSE relay) → Client
```

### Backing Services

- **PostgreSQL**: All persistent data (checkpoints, threads, runs, memory)
- **Redis**: Pub/sub for real-time streaming, ephemeral run data

## Environment Propagation

### LangGraph's Approach

- `langgraph.json` with `"env"` key pointing to `.env` for local dev
- Production: env vars configured in deployment environment (Docker/K8s)
- Specific env vars documented for Agent Server configuration

### Python Subprocess Best Practices

- `subprocess.Popen(env=None)` inherits parent's full `os.environ`
- **Always start from `os.environ.copy()`**, then overlay changes
- **Never build a fresh dict** — loses critical system vars
  (`PATH`, `SystemRoot` on Windows)
- Windows: `env` dict MUST include valid `SystemRoot` for side-by-side
  assemblies

### Our Implementation (Phase 6)

```python
spawn_env = os.environ.copy()
spawn_env["VAULTSPEC_GATEWAY_URL"] = settings.gateway_url
spawn_env["VAULTSPEC_PORT"] = str(settings.port)
spawn_env["VAULTSPEC_WORKER_PORT"] = str(settings.worker_port)
spawn_env["VAULTSPEC_WORKER_HOST"] = settings.worker_host
if settings.internal_token is not None:
    spawn_env["VAULTSPEC_INTERNAL_TOKEN"] = settings.internal_token
subprocess.Popen(cmd, env=spawn_env, ...)
```

This follows the recommended pattern exactly.

## Health Check Patterns

### LangGraph Platform

- System endpoint group for health checks (port 8124)
- Control plane monitors: CPU/memory, container restarts, queue depth,
  API success/error/latency
- Workers acquire leases on runs (prevents double-execution)
- Regular heartbeat signals prevent connection closure
- Stream endpoints can be rejoined on disconnect

### Our Implementation (aligned)

| Component | Pattern | Status |
|-----------|---------|--------|
| `_check_worker_health()` | HTTP GET /health, 2s timeout | Existing |
| `_tcp_port_ready()` | Fast TCP connect (0.5s) before HTTP | Existing |
| `LazyWorkerSpawner` | Double-checked locking, lazy spawn | Existing |
| `WorkerWatchdog` | 5s poll, exponential backoff restart | Existing |
| `WorkerCircuitBreaker` | CLOSED/OPEN/HALF\_OPEN (3-fail) | Existing |
| Startup gateway probe | HTTP GET /health on worker start | Phase 4 |
| CLI pre-flight check | /api/health probe before commands | Phase 7 |
| Heartbeat failure tracking | Consecutive failure counter, escalation | Phase 4 |

## Architecture Comparison

| Aspect | LangGraph Platform | Vaultspec A2A |
|--------|-------------------|---------------|
| Worker lifecycle | Container orchestrator | `subprocess.Popen` |
| Environment | Docker env / K8s ConfigMap | Explicit `env=` dict |
| Health check | Platform monitoring | HTTP probe + circuit breaker |
| Restart | Container restart policy | WorkerWatchdog with backoff |
| Queue | PostgreSQL durable queue | Direct IPC dispatch |
| Scaling | Horizontal (add containers) | Single worker subprocess |

**Key takeaway**: LangGraph Platform doesn't provide subprocess-spawning
patterns (designed for containers). Our auto-spawn is a custom solution
for local/dev use. The health check + circuit breaker + watchdog patterns
cover the gaps a container orchestrator would normally handle.
