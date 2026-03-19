# Library Validation: LangGraph AsyncSqliteSaver — 2026-03-08

## Installed Version

Package: `langgraph-checkpoint-sqlite`
Source: `.venv/Lib/site-packages/langgraph/checkpoint/sqlite/aio.py`

---

## 1. AsyncSqliteSaver.from_conn_string

### Library API

```python
@classmethod
@asynccontextmanager
async def from_conn_string(
    cls, conn_string: str
) -> AsyncIterator[AsyncSqliteSaver]:
    async with aiosqlite.connect(conn_string) as conn:
        yield cls(conn)
```

- Async context manager (must be used with `async with`)
- Accepts a file path string or `":memory:"`
- Creates an `aiosqlite.Connection` and wraps it in `AsyncSqliteSaver`
- Connection is closed on context exit

### Our Usage (`worker/app.py:66-69`)

```python
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
    await checkpointer.setup()
```

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| Import path | CORRECT | `from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver` |
| `from_conn_string` used as async CM | CORRECT | `async with ... as checkpointer` |
| Arg type (str path) | CORRECT | `str(db_path)` converts Path to string |
| Explicit `setup()` call | UNNECESSARY but SAFE | Library auto-calls `setup()` on first query (line 330: `await self.setup()`) |

**Note**: The explicit `setup()` call is technically redundant -- every
`aget_tuple`, `alist`, `aput`, `aput_writes` method starts with
`await self.setup()`. However, calling it explicitly is safe (idempotent,
guarded by `self.lock` and `self.is_setup` flag) and ensures tables exist
before any concurrent operations.

**Verdict**: CORRECT. The explicit `setup()` is safe but not required.

---

## 2. setup() Method

### Library API (`aio.py:275-314`)

```python
async def setup(self) -> None:
    async with self.lock:
        if self.is_setup:
            return
        await _ensure_connected(self.conn)
        async with self.conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS checkpoints (...);
            CREATE TABLE IF NOT EXISTS writes (...);
        """):
            await self.conn.commit()
        self.is_setup = True
```

Key properties:

- **Idempotent**: `self.is_setup` flag prevents re-execution
- **Thread-safe**: Protected by `self.lock` (asyncio.Lock)
- **WAL mode**: Automatically sets `PRAGMA journal_mode=WAL`
- **Creates tables**: `checkpoints` and `writes` with IF NOT EXISTS

### Our Usage

We rely on the library to set WAL mode. This is correct -- the library
handles it in `setup()`.

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| WAL mode | CORRECT | Library sets `PRAGMA journal_mode=WAL` automatically |
| Table creation | CORRECT | Library creates tables if not exist |
| Concurrent access | CORRECT | `asyncio.Lock` prevents concurrent setup |

**Observation**: The library uses `aiosqlite` which runs SQLite in a
background thread. The `asyncio.Lock` protects against concurrent async
callers but does not prevent concurrent process access (e.g., gateway and
worker both opening the same SQLite file). SQLite WAL mode handles this
at the database level.

**Verdict**: CORRECT. No divergence.

---

## 3. Production Warning

The library docstring includes:

> **Warning**: While this class supports asynchronous checkpointing, it is
> not recommended for production workloads due to limitations in SQLite's
> write performance. For production use, consider a more robust database
> like PostgreSQL.

### Our Assessment

This warning is about **high-throughput production** workloads. For our use
case (single-user desktop tool, <10 concurrent threads), SQLite with WAL mode
is appropriate. The shared WAL file between gateway and worker processes is
correctly handled by SQLite's built-in concurrency.

For Docker production deployment with multiple users, this warning becomes
relevant. Consider `langgraph-checkpoint-postgres` for that scenario.

---

## 4. Thread Safety

### Library API

```python
class AsyncSqliteSaver(BaseCheckpointSaver[str]):
    lock: asyncio.Lock
    is_setup: bool

    def __init__(self, conn, *, serde=None):
        self.lock = asyncio.Lock()
        self.loop = asyncio.get_running_loop()
        self.is_setup = False
```

The `self.loop = asyncio.get_running_loop()` captures the event loop at
construction time. Synchronous methods (`get_tuple`, `list`, `put`) use
`asyncio.run_coroutine_threadsafe(coro, self.loop)` to delegate to the async
methods from background threads.

### Our Usage

We only use async methods (`aput`, `aget_tuple`, etc.) via LangGraph's graph
execution. We never call synchronous methods directly.

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| Event loop capture | OK | Our worker runs a single event loop |
| Lock usage | CORRECT | Library handles internally |
| No sync method calls | OK | We use async-only via LangGraph |

**Verdict**: CORRECT. No divergence.

---

## 5. Connection Management

### Library Note

> **Tip**: Remember to close the database connection after executing your
> code, otherwise, you may see the graph "hang" after execution (since the
> program will not exit until the connection is closed).

### Our Usage (`worker/app.py:68`)

```python
async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
    # ... entire worker lifespan ...
```

The `async with` ensures the connection is closed on worker shutdown.
This is exactly the recommended pattern.

**Verdict**: CORRECT.

---

## 6. Test Fixture Usage

### Library Recommendation

Use `":memory:"` for test isolation:

```python
async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
    graph = builder.compile(checkpointer=saver)
```

### Our Test Usage (`api/tests/conftest.py:136`)

```python
checkpointer = MemorySaver()
```

The test conftest uses `MemorySaver` (langgraph in-memory checkpointer)
instead of `AsyncSqliteSaver.from_conn_string(":memory:")`. Per the team
mandate (no mocks/fakes/stubs), this should be replaced with a real
`AsyncSqliteSaver` using either `:memory:` or a temporary file.

**Finding: LIB-VAL-01** (MED): Test conftest uses `MemorySaver` instead of
`AsyncSqliteSaver`. While `MemorySaver` is a real LangGraph checkpointer
(not a mock), it has different behavior from `AsyncSqliteSaver` (no SQLite
tables, no WAL, no lock semantics). Tests using `MemorySaver` do not exercise
the production checkpoint path.

---

## 7. Summary

| Area | Status | Action Needed |
|------|--------|---------------|
| Import path | CORRECT | None |
| `from_conn_string` pattern | CORRECT | None |
| `setup()` call | SAFE but redundant | None (keep for clarity) |
| WAL mode | CORRECT (auto) | None |
| Connection cleanup | CORRECT | None |
| Test checkpointer | DIVERGENT | Replace `MemorySaver` with `AsyncSqliteSaver` in integration tests |
| Production suitability | OK for desktop | Consider Postgres for multi-user Docker |

**Overall**: Production usage is fully aligned with the library API.
One test divergence: `MemorySaver` in test conftest should use real
`AsyncSqliteSaver` for integration tests.
