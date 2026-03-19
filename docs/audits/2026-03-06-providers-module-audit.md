# Providers Module Audit — 2026-03-06

**Auditor:** codebase-researcher (automated)
**Scope:** `src/vaultspec_a2a/providers/` — all 12 source files
**Baseline:** Last audited 2026-03-05 (ACP Hardening Sprint)

---

## Cycle 1 — Full Module Scan

### CRITICAL Findings

#### CRIT-01: `_client_cache` is module-level global with no eviction or invalidation

**File:** `factory.py:23`

```python
_client_cache: dict[tuple, "BaseChatModel"] = {}
```text

This module-level cache stores `ChatOpenAI` instances keyed by `(provider, model_name)`. Issues:

1. **No cache eviction**: entries accumulate forever across the process lifetime
2. **No invalidation on credential change**: if `settings.openai_api_key` changes (env reload, config update), cached clients retain the stale key
3. **Thread safety**: `_client_cache` is a plain dict accessed from potentially concurrent async contexts (multiple graph executions). While CPython's GIL protects dict mutations, the check-then-write pattern (`if cache_key in _client_cache`) is not atomic across an async yield point
4. **Only caches OpenAI/Zhipu**: ACP models (Claude, Gemini) are NOT cached, so this optimization is partial

**Severity:** CRITICAL — stale credentials in cached clients would cause silent auth failures that are extremely hard to diagnose.

#### CRIT-02: `_spawn_acp_process` and `_kill_process_tree` are duplicated 3x

**Files:**

- `acp_chat_model.py:139-241` (production)
- `probes/_protocol.py:30-100` (probe copy)
- Comment in probe says "Mirrors `lib.providers.acp_chat_model._spawn_acp_process`"

These are full copy-paste duplicates (exact same logic, same comments). The probe's docstring still references the old `lib.providers` path, not `vaultspec_a2a.providers`.

**Severity:** CRITICAL (maintainability) — any security fix to process spawning or tree killing must be applied in 2 places. The probe copy is likely to drift.

---

### HIGH Findings

#### HIGH-01: `MockChatModel._astream` silently swallows all exceptions at DEBUG level

**File:** `mock_chat_model.py:179-181`

```python
except Exception as e:
    logger.debug("MockChatModel hit an error in _astream: %s", e)
    raise
```yaml

This is actually fine (it re-raises), but the `_agenerate` method (lines 64-79) has a different concern: it imports `ChatGeneration` and `AIMessage` inside the method body every call. These should be module-level imports.

#### HIGH-02: `MockChatModel` passes `**kwargs` directly to httpx POST payload

**File:** `mock_chat_model.py:119-124`

```python
payload = {
    "model": self.model_name,
    "messages": openai_messages,
    "stream": True,
    **kwargs,
}
```text

Any unexpected kwargs from LangGraph (e.g. `stop`, `run_manager` internal fields) are forwarded to the HTTP payload. The `stop` parameter is consumed by LangChain's `_astream` signature but `**kwargs` may contain arbitrary keys from `ainvoke()` callers. These would be sent to the mock server as JSON, potentially causing 400 errors or being silently ignored.

#### HIGH-03: `MockChatModel` inherits from `ChatOpenAI` but overrides `_astream` with httpx

**File:** `mock_chat_model.py:17, 81-181`

`MockChatModel(ChatOpenAI)` inherits all of ChatOpenAI's initialization, validation, and internal state management, but then completely bypasses it in `_astream` by using raw `httpx.AsyncClient`. This means:

- `ChatOpenAI.__init__` validates `api_key`, sets up `openai.AsyncOpenAI` client, etc. — all wasted
- The `self.openai_api_base` property is used only to extract the URL string
- `streaming=True` is forced in `__init__` but the actual streaming is custom httpx code

This is a leaky abstraction. The class should either use ChatOpenAI's native streaming or not inherit from it.

#### HIGH-04: `_rpc_dispatch` dict is recreated on every `_handle_server_rpc` call

**File:** `acp_chat_model.py:674-683`

```python
_rpc_dispatch: dict[str, Callable[..., Any]] = {
    "session/request_permission": self._on_request_permission,
    ...
}
```python

This dict of 8 entries is constructed fresh on every incoming server RPC. In a typical session with many tool calls, this is called dozens of times. Should be a class attribute or cached in `__init__`.

#### HIGH-05: Probes module docstring references old `lib.providers.probes` import path

**File:** `probes/__init__.py:9-11`

```python
    python -m lib.providers.probes.claude   # ACP subprocess
    python -m lib.providers.probes.gemini   # ACP subprocess
    python -m lib.providers.probes.openai   # HTTP API
```text

Should be `python -m vaultspec_a2a.providers.probes.claude` etc.

---

### MEDIUM Findings

#### MED-01: `fs/read_text_file` uses character-level seek with byte offset parameter

**File:** `acp_chat_model.py:796-812`

```python
offset: int = int(params.get("offset") or 0)
...
def _read() -> str:
    with file_path.open(encoding="utf-8", errors="ignore") as fh:
        if offset:
            fh.seek(offset)
        return fh.read(effective_limit)
```text

The file is opened in text mode (`encoding="utf-8"`) but the ACP protocol sends `offset` as a byte offset. `fh.seek(offset)` in text mode seeks by character count on some platforms, not bytes. This creates inconsistent behavior between platforms and may read incorrect content when the file contains multi-byte UTF-8 characters.

#### MED-02: `terminal/output` reads stdout and stderr sequentially with 0.5s timeouts

**File:** `acp_chat_model.py:988-999`

```python
if process.stdout:
    with suppress(TimeoutError):
        stdout_data = await asyncio.wait_for(
            process.stdout.read(65536), timeout=0.5
        )
if process.stderr:
    with suppress(TimeoutError):
        stderr_data = await asyncio.wait_for(
            process.stderr.read(65536), timeout=0.5
        )
```text

Two sequential 0.5s waits mean `terminal/output` takes up to 1.0s worst case. These could be run concurrently with `asyncio.gather`. More importantly, if stdout has data but stderr blocks (or vice versa), the response is delayed unnecessarily.

#### MED-03: `gemini_auth.py` hardcodes Google OAuth client credentials

**File:** `gemini_auth.py:56-58`

```python
_CLIENT_ID = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
_CLIENT_SECRET = "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"
```text

While the docstring explains these are public "installed application" credentials (intentionally not secret per Google's spec), they are hardcoded rather than read from a config file. If Google rotates these in a gemini-cli update, our code silently fails.

**Mitigation:** The docstring adequately explains this. Low practical risk.

#### MED-04: `AcpError` uses `__slots__` but subclasses also declare `__slots__ = ()`

**Files:** `acp_exceptions.py:71-92`

`AcpError` declares `__slots__ = ("message", "code", "data", "request_id")`. Subclasses (`AcpProtocolError`, `AcpSessionError`, `AcpPromptError`, `AcpAuthError`) each declare `__slots__ = ()`. This is correct Python for slots inheritance, but `AcpError.message` shadows `BaseException.args[0]` since `super().__init__(self._format_message())` also sets `args`. The `message` slot and `args[0]` can diverge if someone accesses `str(exc)` vs `exc.message`.

#### MED-05: Probe `_ProbeSession.run_loop` does not handle rate_limit_event in the main stdout loop

**File:** `probes/_protocol.py:254-303`

The `run_loop` method processes responses and `session/update` notifications, but `rate_limit_event` parsing only happens in `read_stderr`. If the ACP subprocess emits rate limit events on stdout (which some versions do), they would be silently ignored.

#### MED-06: `ProviderFactory.create` unreachable final `raise ValueError`

**File:** `factory.py:259-260`

```python
logger.error("Failed to instantiate: Unsupported provider %s", provider)
raise ValueError(f"Unsupported provider: {provider}")
```text

This code is unreachable because the `supported` set check at line 104-107 already catches unsupported providers. The early guard covers all enum members. Dead code.

---

### LOW Findings

#### LOW-01: `_TERMINAL_COMMAND_ALLOWLIST` does not include common tools like `cargo`, `go`, `java`, `ruby`

**File:** `acp_chat_model.py:94-117`

The allowlist focuses on Python/JS/shell toolchains. If agents need to work with Rust, Go, Java, or Ruby workspaces, terminal commands will be rejected. This is security-conscious (least privilege) but may need expansion based on use cases.

#### LOW-02: `AcpChatModel._astream` creates a new subprocess per invocation

**File:** `acp_chat_model.py:337-408`

Every `ainvoke` or `_astream` call spawns a new ACP subprocess, goes through the full `initialize` -> `session/new` -> `session/prompt` lifecycle, and kills the process afterward. The cold-start overhead is significant (up to 60s for Claude ACP). Session reuse via `session_id` / `session/load` is supported in the protocol but not used by the current implementation.

#### LOW-03: `_SHELL_METACHAR_RE` misses some injection vectors

**File:** `acp_chat_model.py:122`

```python
_SHELL_METACHAR_RE = re.compile(r"[|&;`$()<>]")
```text

This misses `\n` (newline injection), `#` (comment injection), `{` `}` (brace expansion), and `!` (history expansion in bash). While `create_subprocess_exec` doesn't invoke a shell, the comment says this is "defense-in-depth" — the depth could be deeper.

#### LOW-04: Probe `__init__.py` docstring references old module path

**File:** `probes/__init__.py:9`

Says `python -m lib.providers.probes.claude` — should be `python -m vaultspec_a2a.providers.probes.claude`. Same stale path reference as HIGH-05.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 2     | Stale credential cache, duplicated spawn/kill code |
| HIGH     | 5     | MockChatModel architecture, perf, stale paths |
| MEDIUM   | 6     | Seek semantics, sequential I/O, dead code |
| LOW      | 4     | Allowlist gaps, cold start, stale docs |

### Recommended Fix Priority

1. **CRIT-01**: Either remove `_client_cache` entirely (it only caches OpenAI/Zhipu) or implement proper invalidation with TTL/credential fingerprinting.
2. **CRIT-02**: Extract `_spawn_acp_process` and `_kill_process_tree` into a shared `_subprocess.py` module imported by both `acp_chat_model.py` and `probes/_protocol.py`.
3. **HIGH-03**: Consider making MockChatModel a standalone `BaseChatModel` subclass rather than inheriting from `ChatOpenAI`.
4. **HIGH-05 + LOW-04**: Fix stale `lib.providers` references to `vaultspec_a2a.providers`.

---

## Cycle 2 — Re-audit (2026-03-06)

All findings remain **OPEN**. Task #9 (`Fix providers CRIT-01/02 and HIGH-05`) is now in_progress.

| Finding | Status | Notes |
|---------|--------|-------|
| CRIT-01 | OPEN | `_client_cache` still has no eviction/invalidation (factory.py:23) |
| CRIT-02 | OPEN | `_spawn_acp_process`/`_kill_process_tree` still duplicated in probes/_protocol.py |
| HIGH-01 through HIGH-05 | OPEN | -- |
| MED-01 through MED-06 | OPEN | -- |
| LOW-01 through LOW-04 | OPEN | -- |

Stale `lib.providers` paths (HIGH-05, LOW-04) will be covered by task #19 (batch path fix).

---

## Cycle 3 — Deep Re-audit (2026-03-06)

Focus: ACP subprocess environment handling, factory correctness post-migration, probe CLI integrity, stale paths.

### Verified Fixes

| Finding | Description | Status |
|---------|-------------|--------|
| CRIT-01 | `_client_cache` no eviction/invalidation | **FIXED** -- `_client_cache` removed entirely from `factory.py`. No module-level client cache exists anymore. |

### Partial Fixes

| Finding | Description | Status |
|---------|-------------|--------|
| CRIT-02 | Duplicated `_spawn_acp_process`/`_kill_process_tree` | **PARTIAL** -- `_subprocess.py` extracted as shared module (lines 24-121). `acp_chat_model.py:139-140` imports from it. **BUT** `probes/_protocol.py:30-100` still has its own local copies that do NOT use the shared module. The probe copies also lack `use_exec` support (binary backend). Docstrings still reference `lib.providers.acp_chat_model`. |

### New Findings

#### NEW-01 (HIGH): Probe `_spawn_acp_process` diverges from production `_subprocess.spawn_acp_process`

**Files:** `probes/_protocol.py:30-57` vs `_subprocess.py:24-69`

The shared `_subprocess.py` has evolved:

- Supports `use_exec: bool = False` parameter for binary backend (`create_subprocess_exec` on Windows)
- Type annotation uses `dict[str, Any]` (vs probe's `dict[str, object]`)

The probe's copy at `_protocol.py:30-57`:

- Always uses `create_subprocess_shell` on Windows (no `use_exec` support)
- Docstring line 37: `Mirrors ``lib.providers.acp_chat_model._spawn_acp_process``` — stale path AND no longer accurate (production code uses`_subprocess.py`)

This means binary backend probes (`--backend binary`) always go through `cmd.exe` shim on Windows even though the production code uses `create_subprocess_exec` for binaries. This is a correctness difference between probe and production behavior.

#### NEW-02 (HIGH): Probe `_kill_process_tree` missing SIGTERM warning log

**Files:** `probes/_protocol.py:60-100` vs `_subprocess.py:72-121`

Production `_subprocess.py:109-113` logs a warning before escalating from SIGTERM to SIGKILL:

```python
logger.warning(
    "ACP process %s did not exit after SIGTERM; "
    "escalating to SIGKILL",
    process.pid,
)
```text

Probe copy at `_protocol.py:93-96` silently escalates. Minor operational difference but indicates drift.

#### NEW-03 (MEDIUM): Probe env construction does not use `resolve_env_vars()`

**File:** `probes/_protocol.py:371`

```python
env = os.environ.copy()
```text

The probe builds its environment from raw `os.environ.copy()` + manual scrubbing logic (lines 371-409), duplicating the credential scrubbing that `resolve_env_vars()` in `workspace/environment.py` already handles comprehensively. The probe's manual scrub misses:

- `VAULTSPEC_*` prefix scrubbing (done in `resolve_env_vars()` line 112)
- `GOOGLE_API_KEY`, `AWS_SECRET_ACCESS_KEY`, `AZURE_OPENAI_API_KEY` scrubbing
- `LANGCHAIN_API_KEY`, `LANGCHAIN_TRACING_V2` scrubbing

While probes are manual dev tools (lower security bar), the inconsistency means the probe subprocess inherits secrets that production ACP subprocesses do not.

#### NEW-04 (MEDIUM): `__init__.py` facade docstring still references `lib.providers`

**File:** `providers/__init__.py:3`

```python
Facade re-exporting all public types from the ``lib.providers`` subpackage.
```python

Should be `vaultspec_a2a.providers`.

#### NEW-05 (MEDIUM): Stale `lib.` docstring paths in all 4 probe modules

**Files:**

- `probes/gemini.py:5` — `:func:`~lib.providers.gemini_auth.refresh_gemini_token``
- `probes/gemini.py:10` — `python -m lib.providers.probes.gemini`
- `probes/openai.py:5` — `:class:`~lib.providers.factory.ProviderFactory``
- `probes/openai.py:9` — `python -m lib.providers.probes.openai`
- `probes/openai.py:36` — `:attr:`~lib.core.config.Settings.openai_api_key``
- `probes/zhipu.py:6` — `:class:`~lib.providers.factory.ProviderFactory``
- `probes/zhipu.py:10` — `python -m lib.providers.probes.zhipu`
- `probes/zhipu.py:37` — `:attr:`~lib.core.config.Settings.zhipu_api_key``
- `probes/_protocol.py:37` — `lib.providers.acp_chat_model._spawn_acp_process`
- `probes/_protocol.py:63` — `lib.providers.acp_chat_model._kill_process_tree`

Total: 10 stale `lib.` references across 5 probe files. These are all task #19 scope.

#### NEW-06 (LOW): `_subprocess.py` not exported from providers facade

**File:** `providers/__init__.py`

`spawn_acp_process` and `kill_process_tree` from `_subprocess.py` are not in `__init__.py` or `__all__`. By convention the leading underscore on the module name indicates internal-only, so this is acceptable, but `probes/_protocol.py` could import from `_subprocess.py` instead of maintaining its own copies (see CRIT-02 partial fix).

### ANTHROPIC_LOG Scrub Verification

**Result: CORRECTLY HANDLED in production.**

- `workspace/environment.py:88`: `ANTHROPIC_LOG` is in the `scrub_keys` frozenset
- `acp_chat_model.py:256`: calls `resolve_env_vars(_ws_path)` which strips ANTHROPIC_LOG
- `probes/_protocol.py:379`: independently strips `ANTHROPIC_LOG` via `env.pop()`

Both production and probe paths correctly prevent ANTHROPIC_LOG from corrupting ACP JSON-RPC streams.

### Factory Post-Migration Verification

**Result: CLEAN.**

- `factory.py` imports all use relative imports (`from ..core.config`, `from ..utils.enums`)
- No stale `lib.` import paths
- `_client_cache` fully removed (CRIT-01 fixed)
- `_PROJECT_ROOT` path resolution correct: `Path(__file__).resolve().parent.parent.parent.parent` = 4 levels up from `factory.py` = project root
- MED-06 unreachable `raise ValueError` at factory.py:246-247 still present (dead code after line 102-104 guard)

### Cycle 3 Summary

| Finding | Severity | Status |
|---------|----------|--------|
| CRIT-01 | CRITICAL | **FIXED** -- `_client_cache` removed |
| CRIT-02 | CRITICAL | **PARTIAL** -- `_subprocess.py` extracted but probes still duplicate |
| HIGH-01 | HIGH | OPEN -- inline imports in MockChatModel._agenerate |
| HIGH-02 | HIGH | OPEN -- `**kwargs` forwarded to httpx payload |
| HIGH-03 | HIGH | OPEN -- MockChatModel inherits ChatOpenAI (task #13) |
| HIGH-04 | HIGH | OPEN -- `_rpc_dispatch` recreated every call |
| HIGH-05 | HIGH | OPEN -- stale `lib.providers` paths (task #19) |
| NEW-01 | HIGH | **NEW** -- probe _spawn diverges from production (no use_exec) |
| NEW-02 | HIGH | **NEW** -- probe _kill missing SIGTERM warning log |
| NEW-03 | MEDIUM | **NEW** -- probe env construction bypasses resolve_env_vars() |
| NEW-04 | MEDIUM | **NEW** -- facade docstring references `lib.providers` |
| NEW-05 | MEDIUM | **NEW** -- 10 stale `lib.` paths across 5 probe files |
| MED-01 through MED-06 | MEDIUM | OPEN |
| NEW-06 | LOW | **NEW** -- _subprocess.py not in facade (acceptable) |
| LOW-01 through LOW-04 | LOW | OPEN |

**Remaining open: 0 CRIT (1 fixed, 1 partial), 7 HIGH (5 original + 2 new), 9 MED (6 original + 3 new), 5 LOW (4 original + 1 new)**

**Recommended action for CRIT-02 completion:** Have `probes/_protocol.py` import `spawn_acp_process` and `kill_process_tree` from `.._subprocess` instead of maintaining local copies. This eliminates the duplication AND picks up `use_exec` support for binary probes.
