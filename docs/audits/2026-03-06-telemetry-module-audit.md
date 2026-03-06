# Telemetry Module Audit — 2026-03-06

**Auditor:** codebase-researcher (automated)
**Scope:** `src/vaultspec_a2a/telemetry/` — 3 source files (instrumentation.py, middleware.py, __init__.py)
**Baseline:** No prior dedicated audit for this module.

---

## Cycle 1 — Full Module Scan

### CRITICAL Findings

*None identified.* The module is well-structured with proper credential safety (ADR-002 compliant — no secrets read/logged/emitted).

---

### HIGH Findings

#### HIGH-01: `_LANGSMITH_ENABLED` and `_LANGSMITH_PROJECT` read legacy `LANGCHAIN_*` env vars

**File:** `instrumentation.py:78-83`

```python
_LANGSMITH_ENABLED = os.environ.get("LANGCHAIN_TRACING_V2", "").lower() in (...)
_LANGSMITH_PROJECT = os.environ.get("LANGCHAIN_PROJECT", "default")
```

The ADR-027 compliance sprint established `LANGSMITH_*` as the canonical env var names, with `LANGCHAIN_*` as legacy aliases. The Settings model in `core/config.py` uses `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` as primary names with `AliasChoices` for legacy fallback.

But `instrumentation.py` only reads the legacy names — if a user sets only `LANGSMITH_TRACING=true`, LangSmith detection in the telemetry module will fail (reads `LANGCHAIN_TRACING_V2` which won't be set).

The docstring at lines 26-28 also only documents the legacy names.

**Impact:** Users following the canonical naming convention from Settings will have LangSmith detection fail silently in the telemetry module while LangSmith actually works (because the SDK reads both).

#### HIGH-02: `middleware.py` imports private `_SDK_DISABLED` from `instrumentation.py`

**File:** `middleware.py:38`

```python
from .instrumentation import _SDK_DISABLED, get_tracer
```

Cross-module import of a private symbol (leading underscore). If `_SDK_DISABLED` is renamed or refactored, `middleware.py` breaks. This should be exposed as a public function (`is_sdk_disabled()`) or a public constant.

---

### MEDIUM Findings

#### MED-01: Module-level `os.environ` reads are import-time constants

**File:** `instrumentation.py:60-83`

Seven `os.environ.get()` calls at module level create constants evaluated once at import time. This is explicitly documented (comments at lines 50-59) and accepted as an ENV-BYPASS exception. However:
- Tests cannot override these values without subprocess isolation
- The test at `test_telemetry.py:141` uses `monkeypatch.delenv("LANGCHAIN_TRACING_V2")` which has NO effect since `_LANGSMITH_ENABLED` was already evaluated at import time

The test comment at line 115 acknowledges this: "Note: _LANGSMITH_ENABLED is evaluated at import time from LANGCHAIN_TRACING_V2." But the monkeypatch at line 141 is still dead code that gives a false sense of test coverage.

#### MED-02: `TelemetryMiddleware.dispatch` exception handler uses `span` from enclosing scope

**File:** `middleware.py:150-154`

```python
except Exception as exc:
    # M33: use `span` directly — get_current_span() is redundant here
    span.set_status(StatusCode.ERROR, str(exc))
    span.record_exception(exc)
    raise
```

The `span` variable from the `with` block (line 132) is referenced in the `except` clause. If the `with` block's `start_as_current_span` itself raises (e.g., SDK initialization error), `span` would be unbound, causing `NameError`. This is extremely unlikely in practice since `start_as_current_span` is well-tested OTel SDK code, but the M33 comment suggests this was a conscious simplification.

#### MED-03: `ws_span` skips `_SDK_DISABLED` check differently from `TelemetryMiddleware`

**Files:** `middleware.py:190-191` vs `middleware.py:117-118`

`ws_span` explicitly checks `_SDK_DISABLED` and yields a `NonRecordingSpan` (line 190-191). `TelemetryMiddleware.dispatch` does NOT check `_SDK_DISABLED` — it always creates spans via `_get_tracer()`. When SDK is disabled, the tracer returns no-op spans anyway, so the behavior is equivalent, but the inconsistency suggests the `ws_span` check is redundant or the middleware check is missing.

#### MED-04: `_check_sdk()` docstring says "opentelemetry-sdk is a mandatory dependency" but body checks availability

**File:** `instrumentation.py:117-119`

```python
def _check_sdk() -> bool:
    """Return True — opentelemetry-sdk is a mandatory dependency (ADR-015)."""
    return importlib.util.find_spec("opentelemetry.sdk.trace") is not None
```

If the SDK is mandatory (ADR-015), why check if it's installed? The docstring and body contradict. Either the SDK should be imported directly (and crash if missing) or the docstring should say "Check if the optional SDK is available."

---

### LOW Findings

#### LOW-01: No stale `lib.` import paths

All imports use proper relative patterns or `vaultspec_a2a.*` absolute paths. Clean migration.

#### LOW-02: `_EXCLUDED_PATHS` missing `/api/v1/health` variant

**File:** `middleware.py:65-72`

The excluded paths set only contains root-level health endpoints (`/health`, `/healthz`, `/ready`, `/metrics`). If the API mounts under a prefix (e.g., `/api/v1/`), health checks would still be traced.

#### LOW-03: `configure_telemetry` docstring example uses `@asynccontextmanager` without import

**File:** `instrumentation.py:236`

Minor: the example code in the docstring uses `@asynccontextmanager` but doesn't show the import.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 0     | -- |
| HIGH     | 2     | Legacy LANGCHAIN_* env vars, private cross-module import |
| MEDIUM   | 4     | Import-time constants, dead test code, SDK check contradiction |
| LOW      | 3     | Clean migration, excluded paths gap, docstring nit |

### Assessment

The telemetry module is well-architected with proper separation of concerns:
- `instrumentation.py`: OTel SDK setup (TracerProvider, MeterProvider)
- `middleware.py`: HTTP middleware + WS span helper + context injection
- Facade in `__init__.py` exports all public symbols correctly

No security concerns. The main issue is the `LANGCHAIN_*` vs `LANGSMITH_*` naming inconsistency (HIGH-01) which could cause silent failure for users following the canonical Settings naming.

### Recommended Fix Priority

1. **HIGH-01**: Read both `LANGSMITH_TRACING` and `LANGCHAIN_TRACING_V2` (with LANGSMITH preferred), matching the Settings fallback pattern.
2. **HIGH-02**: Expose `_SDK_DISABLED` as a public `is_sdk_disabled()` function or `SDK_DISABLED` constant.
3. **MED-01**: Remove the dead `monkeypatch.delenv` from test — it does nothing.
4. **MED-04**: Fix the `_check_sdk()` docstring to accurately describe its purpose.

---

## Cycle 2 — Fix Verification & Cross-Module Consistency (2026-03-06)

**Focus:** Verify whether Cycle 1 findings were addressed, check cross-module consistency with the broader ADR-027 naming migration, and validate facade completeness.

### Fix Status: ALL CYCLE 1 FINDINGS STILL OPEN

No fixes have been applied to the telemetry module since Cycle 1. All 2 HIGH, 4 MED, 3 LOW findings remain.

### Cross-Module Consistency

#### HIGH-01 Correlation: LANGCHAIN_* vs LANGSMITH_* inconsistency is systemic

The telemetry module's HIGH-01 (`instrumentation.py:78-83` reads only `LANGCHAIN_TRACING_V2`) is part of a broader pattern:

| Module | File | Reads | Status |
|--------|------|-------|--------|
| telemetry | `instrumentation.py:78` | `LANGCHAIN_TRACING_V2` only | **BROKEN** for `LANGSMITH_TRACING` users |
| telemetry | `instrumentation.py:83` | `LANGCHAIN_PROJECT` only | **BROKEN** for `LANGSMITH_PROJECT` users |
| utils | `trace.py:34-35` | Both `LANGSMITH_*` and `LANGCHAIN_*` | CORRECT |
| core | `config.py` (Settings) | Both via `AliasChoices` | CORRECT |
| workspace | `environment.py:82` | `LANGCHAIN_API_KEY` in scrub list | **INCOMPLETE** — missing `LANGSMITH_API_KEY` |

The telemetry module is the ONLY module that reads exclusively legacy names. `trace.py` in utils already reads both — the fix pattern exists in-repo.

### Facade Completeness

`telemetry/__init__.py` exports 7 symbols: `TelemetryConfig`, `TelemetryMiddleware`, `configure_telemetry`, `get_meter`, `get_tracer`, `inject_trace_context`, `ws_span`.

**Not exported (by design):**
- `_SDK_DISABLED` — private constant, consumed by `middleware.py` via direct import. Per HIGH-02, should be exposed as `is_sdk_disabled()` or `SDK_DISABLED`.
- `_get_tracer()` — internal helper, not public. Correct to exclude.

### Test Coverage Verification

`telemetry/tests/test_telemetry.py` line 102: `monkeypatch.setenv("OTEL_SDK_DISABLED", "true")` — this sets the env var AFTER `_SDK_DISABLED` was evaluated at import time. The test comment at line 107 acknowledges this. The test still passes because it only checks the `TelemetryConfig.sdk_enabled` field (which is computed from the live `_SDK_DISABLED` value at configure-time), not re-evaluating `_SDK_DISABLED` itself.

However, `monkeypatch.delenv("LANGCHAIN_TRACING_V2")` at line 141 (identified in MED-01) is genuinely dead code — it has no effect on the already-evaluated `_LANGSMITH_ENABLED` constant.

### Cycle 2 Summary

| Status | Finding | Notes |
|--------|---------|-------|
| STILL OPEN | HIGH-01 | LANGCHAIN_* only reads — systemic, see cross-module table above |
| STILL OPEN | HIGH-02 | `_SDK_DISABLED` private cross-module import |
| STILL OPEN | MED-01 | Dead monkeypatch in test |
| STILL OPEN | MED-02 | span variable scoping |
| STILL OPEN | MED-03 | Inconsistent `_SDK_DISABLED` check in `ws_span` vs middleware |
| STILL OPEN | MED-04 | `_check_sdk()` docstring contradiction |
| STILL OPEN | LOW-01/02/03 | Minor issues |

**No new findings.** The module is stable but the HIGH-01 naming inconsistency should be prioritized as it affects user experience for anyone following the canonical `LANGSMITH_*` naming from Settings/ADR-027.
