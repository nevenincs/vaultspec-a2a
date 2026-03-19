# Library Validation: httpx AsyncClient — 2026-03-08

## Installed Version

Package: `httpx`
Source: `.venv/Lib/site-packages/httpx/_config.py` (Timeout class)
Source: `.venv/Lib/site-packages/httpx/_transports/mock.py` (MockTransport)

---

## 1. Timeout Configuration

### Library API (`_config.py:72-130`)

```python
class Timeout:
    def __init__(
        self,
        timeout: TimeoutTypes | UnsetType = UNSET,
        *,
        connect: None | float | UnsetType = UNSET,
        read: None | float | UnsetType = UNSET,
        write: None | float | UnsetType = UNSET,
        pool: None | float | UnsetType = UNSET,
    ) -> None:
```text

Usage patterns from docstring:

```python
Timeout(None)               # No timeouts
Timeout(5.0)                # 5s timeout on all operations
Timeout(None, connect=5.0)  # 5s timeout on connect, no other timeouts
Timeout(5.0, connect=10.0)  # 10s timeout on connect, 5s elsewhere
Timeout(5.0, pool=None)     # No pool timeout, 5s elsewhere
```yaml

Default httpx timeout: 5.0 seconds on all operations.

### Our Usage

**MCP shared client** (`protocols/mcp/server.py:118-119`):

```python
_shared_client = httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=5.0),
)
```text

**Worker IPC bridge** (`worker/ipc.py:66-69`):

```python
self._client = httpx.AsyncClient(
    base_url=self._api_url,
    timeout=httpx.Timeout(10.0, connect=5.0),
    headers=headers,
)
```text

**Gateway health check** (`protocols/mcp/server.py:228`):

```python
async with httpx.AsyncClient() as client:
    resp = await client.get(
        f"{api_base}/health",
        timeout=_GATEWAY_HEALTH_TIMEOUT,  # 2.0
    )
```text

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| `Timeout(30.0, connect=5.0)` | CORRECT | 30s default, 5s connect override |
| `Timeout(10.0, connect=5.0)` | CORRECT | 10s default, 5s connect override |
| Per-request `timeout=2.0` | CORRECT | Float passed directly, becomes `Timeout(2.0)` |
| No deprecated patterns | CORRECT | No tuple-style timeouts used |

**Best practice note**: The MCP shared client uses 30s default timeout,
which is generous. Individual tools override this with per-request timeouts
(`_MCP_CREATE_TIMEOUT = 30.0`, `_MCP_QUERY_TIMEOUT = 15.0`). This is correct
-- per-request timeouts override the client default.

**Verdict**: CORRECT. No divergence.

---

## 2. MockTransport

### Library API (`_transports/mock.py`)

```python
class MockTransport(AsyncBaseTransport, BaseTransport):
    def __init__(self, handler: SyncHandler | AsyncHandler) -> None:
        self.handler = handler

    def handle_request(self, request: Request) -> Response:
        request.read()
        response = self.handler(request)
        ...

    async def handle_async_request(self, request: Request) -> Response:
        await request.aread()
        response = self.handler(request)
        if not isinstance(response, Response):
            response = await response
        return response
```yaml

Key: MockTransport accepts either sync or async handlers. For `AsyncClient`,
it calls `handle_async_request`.

### Our Usage (`api/tests/conftest.py:87-107`)

```python
def _make_test_worker_transport(captured):
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/dispatch" and request.method == "POST":
            body = _json.loads(request.content)
            captured.requests.append(body)
            return httpx.Response(200, json={...})
        return httpx.Response(404, json={"detail": "Not found"})
    return httpx.MockTransport(_handler)
```text

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| Sync handler with AsyncClient | CORRECT | Library wraps sync handler for async use |
| `request.content` access | CORRECT | Content is read via `aread()` before handler is called |
| Return `httpx.Response` | CORRECT | Matches expected return type |

**Finding: LIB-VAL-02** (team mandate): The test conftest uses
`httpx.MockTransport` to simulate the worker HTTP API. Per the team mandate
("NO MOCKS. NO FAKES. NO STUBS."), this should be replaced with a real
worker subprocess. The `MockTransport` is correctly used from a library
perspective but violates the project's testing policy.

**Verdict**: Library usage is CORRECT, but violates team testing mandate.

---

## 3. AsyncClient Configuration

### Library API

```python
httpx.AsyncClient(
    transport=...,         # BaseTransport override
    base_url=...,          # Prepended to relative URLs
    timeout=...,           # Timeout config
    headers=...,           # Default headers
)
```text

### Our Usage Across Codebase

**MCP shared client** (`protocols/mcp/server.py:118`):

```python
httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
```text

No `base_url` -- uses full URLs in each request. This is intentional because
the API base URL comes from runtime settings.

**Worker bridge** (`worker/ipc.py:66-69`):

```python
httpx.AsyncClient(
    base_url=self._api_url,
    timeout=httpx.Timeout(10.0, connect=5.0),
    headers=headers,
)
```text

Uses `base_url` because all requests go to the same gateway.

**Test worker client** (`api/tests/conftest.py:141-143`):

```python
worker_client = httpx.AsyncClient(
    transport=transport, base_url="http://test-worker:8001"
)
```text

Uses `transport` override (MockTransport) + `base_url`.

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| No `base_url` in MCP client | CORRECT | Intentional for runtime URL flexibility |
| `base_url` in worker bridge | CORRECT | All requests go to same gateway |
| `transport` override in tests | CORRECT (library), VIOLATES mandate | MockTransport is valid httpx API |
| `headers` for auth | CORRECT | Bearer token in Authorization header |

---

## 4. Connection Lifecycle

### Library API

`httpx.AsyncClient` should be used as an async context manager or closed
explicitly:

```python
async with httpx.AsyncClient() as client:
    ...

# or
client = httpx.AsyncClient()
try:
    ...
finally:
    await client.aclose()
```text

### Our Usage

**MCP shared client**: Module-level singleton, never properly closed.
`_reset_client()` attempts cleanup but uses `_transport.close()` (sync)
instead of `await client.aclose()` (async).

```python
def _reset_client() -> None:
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        with contextlib.suppress(Exception):
            _shared_client._transport.close()  # sync close
    _shared_client = None
```yaml

**Finding: LIB-VAL-03** (LOW): `_reset_client()` uses synchronous
`_transport.close()` instead of `await client.aclose()`. This is a test-only
helper (not called in production), so impact is minimal. In production, the
client lives for the process lifetime and is cleaned up by process exit.

**Worker bridge**: Properly closed via `await self._client.aclose()` in
`WorkerBridge.close()`.

**Health check probes**: Use `async with httpx.AsyncClient() as client:`
pattern -- correct.

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| Worker bridge cleanup | CORRECT | `await self._client.aclose()` |
| Health check probes | CORRECT | `async with` pattern |
| MCP shared client | ACCEPTABLE | Lives for process lifetime; sync close in test helper only |

---

## 5. AsyncHTTPTransport (Retry)

### Library API

```python
httpx.AsyncHTTPTransport(retries=3)
```text

Retries only `ConnectError` and `ConnectTimeout` -- does NOT retry on HTTP
errors, read timeouts, or write failures.

### Our Usage

We do NOT use `AsyncHTTPTransport(retries=...)`. Retry logic is implemented
at the application level:

- Worker bridge: `_MAX_FLUSH_RETRIES = 3` with exponential backoff
  (`worker/ipc.py:30-33`)
- MCP health polling: Exponential backoff in `_spawn_gateway()`
  (`protocols/mcp/server.py:278-322`)

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| No transport-level retries | OK | Application-level retry is more flexible |
| Application retry logic | CORRECT | Handles all error types, not just ConnectError |

**Verdict**: CORRECT. Application-level retry is the better pattern for our
use case (we need to retry on HTTP errors too, not just connection errors).

---

## 6. Summary

| Area | Status | Action Needed |
|------|--------|---------------|
| Timeout configuration | CORRECT | None |
| MockTransport usage | CORRECT (library), VIOLATES team mandate | Replace with real subprocess in tests |
| AsyncClient config | CORRECT | None |
| Connection lifecycle | ACCEPTABLE | LOW: sync close in test helper |
| Retry pattern | CORRECT | Application-level retry is better |
| Deprecated patterns | NONE FOUND | None |

**Findings**:

- **LIB-VAL-02** (mandate): MockTransport in conftest violates no-mock mandate
- **LIB-VAL-03** (LOW): Sync `_transport.close()` in test helper (not production)

**Overall**: httpx usage is fully correct and follows library best practices.
The one issue (MockTransport) is a testing policy violation, not a library
misuse.
