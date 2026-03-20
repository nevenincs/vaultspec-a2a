# Port Configuration Audit

**Date**: 2026-03-20
**Severity**: CRITICAL — port overrides silently do not work
**Scope**: Every service port across config, Justfile, Docker Compose, and doctor.py

---

## Summary

Port configuration is broken across the control surface. Setting
`VAULTSPEC_PORT=9000` in `.env` has **no effect** when using
`just dev service start gateway` because the Justfile passes `--port 8000`
as a literal to uvicorn, overriding the environment. The same is true for
the worker port. Stop/kill recipes identify processes by scanning for the
literal port string, so they also fail on non-default ports.

The Python `Settings` auto-derivation (gateway_url, worker_url from
host+port) works correctly — but only in the auto-spawn code path. The
Justfile bypasses it entirely.

---

## Port Map

| Port | Service | Env Var | Config Key | Justfile Hardcoded | Docker Hardcoded | Override Works? | Conflict Detection |
|------|---------|---------|------------|-------------------|-----------------|-----------------|-------------------|
| 8000 | Gateway | `VAULTSPEC_PORT` | `port` | YES (`--port 8000`) | YES (`8000:8000`) | NO (Justfile overrides env) | None |
| 8001 | Worker | `VAULTSPEC_WORKER_PORT` | `worker_port` | YES (`--port 8001`) | YES (`8001:8001`) | NO (Justfile overrides env) | None |
| 5173 | Vite UI | None | None in Settings | No recipe | YES (`5173:5173`) | N/A | doctor.py hardcodes `:5173` |
| 4317 | Jaeger OTLP | `OTEL_EXPORTER_OTLP_ENDPOINT` | None | YES (`-p 4317:4317`) | YES | No runtime reconfig | None |
| 16686 | Jaeger UI | None | None | YES (`-p 16686:16686`) | YES | N/A (UI only) | None |
| 13133 | Jaeger health | None | None | YES (`-p 13133:13133`) | YES | N/A | doctor.py probes WRONG port (14269) |
| 5432 | PostgreSQL | URL-embedded | None | Not referenced | Service-only | URL-embedded | None |
| 8100 | VidaiMock | `MOCK_API_BASE` (URL) | None | Via compose | YES (`8100:8100`) | URL override only | **COLLISION with MCP** |
| 8100 | MCP server | `VAULTSPEC_MCP_PORT` | `mcp_port` | No (passthrough) | No compose | Yes | **COLLISION with VidaiMock** |

---

## Critical Gaps

### Gap 1 [CRIT]: Justfile start recipes hardcode ports — env overrides silently ignored

`_dev-service-start-gateway` passes `--port 8000` literally to uvicorn.
`_dev-service-start-worker` passes `--port 8001` literally to uvicorn.

Setting `VAULTSPEC_PORT=9000` in `.env` does nothing. The uvicorn CLI flag
wins over the env var. The user thinks they've changed the port but the
service still binds to 8000.

**Fix**: Justfile recipes must read from env or delegate to Python:

```text
_dev-service-start-gateway:
    uv run uvicorn vaultspec_a2a.api.app:create_app --factory --reload \
        --host 127.0.0.1 --port ${VAULTSPEC_PORT:-8000}
```

Or remove `--port` entirely and let Settings handle it via the app factory.

### Gap 2 [CRIT]: Stop/kill recipes identify processes by literal port string

Stop and kill recipes use `$_.CommandLine -match "8000"` to find the gateway
process. If the gateway runs on port 9000, the kill recipe finds nothing.

**Fix**: Read port from env in the recipe, or use a PID file written at start.

### Gap 3 [HIGH]: MCP and VidaiMock share port 8100 — no detection

Both default to `:8100`. Running both locally causes a silent bind failure
for whichever starts second. Not documented anywhere.

**Fix**: Change MCP default to a different port (e.g., 8200), or add a
startup collision check.

### Gap 4 [HIGH]: Doctor.py probes wrong Jaeger health port

Doctor.py probes `:14269` (legacy Jaeger admin port). The Justfile and
Docker Compose expose `:13133` (OpenTelemetry health extension). Doctor
always reports Jaeger as "not running" even when it's healthy.

**Fix**: Change doctor.py to probe `:13133/status` (matching Justfile and
compose healthchecks).

### Gap 5 [MED]: Docker Compose hardcodes all port mappings — no env interpolation

All compose files use literal port strings: `'8000:8000'`, `'8001:8001'`,
etc. No `${VAULTSPEC_PORT:-8000}:8000` patterns. Changing ports requires
editing compose files directly.

**Fix**: Use env interpolation with defaults in compose files.

### Gap 6 [MED]: Vite port not in Settings — CORS origins hardcoded

Vite's bind port has no config key. CORS defaults contain hardcoded
`http://localhost:5173`. If Vite auto-increments to 5174 on port conflict,
CORS will reject requests.

**Fix**: Add `VAULTSPEC_CORS_ALLOWED_ORIGINS` documentation or auto-include
Vite's actual port.

### Gap 7 [MED]: PostgreSQL port only configurable via URL string

No `VAULTSPEC_DB_PORT` setting. Port is embedded in `VAULTSPEC_DATABASE_URL`.
Compose files hardcode `@postgres:5432` inline. Can't remap without editing
the full URL.

### Gap 8 [LOW]: OTLP endpoint is import-time constant

`OTEL_EXPORTER_OTLP_ENDPOINT` is read once at module import. Documented
and intentional, but means `.env` changes require process restart.

---

## Recommendations (Priority Order)

1. **Justfile must read ports from env** (Gap 1+2) — single most impactful fix
2. **Change MCP default port** (Gap 3) — prevent silent collision
3. **Fix doctor.py Jaeger probe** (Gap 4) — health checks must be correct
4. **Docker Compose env interpolation** (Gap 5) — production configurability
5. **Document the port layout** (all gaps) — `.env.example` must explain every port
