---
date: 2026-02-27
type: research
feature: a2a-langgraph-patterns
description: 'Reference patterns for A2A protocol implementation on top of LangGraph.'
---

# A2A SDK & LangGraph Reference Patterns for Compliance Audit

**Date:** 2026-02-27
**Author:** ref-a2a (automated research agent)
**Purpose:** Canonical reference patterns from A2A Python SDK and LangGraph to
resolve findings from the implementation compliance audit.

---

## Issue 1: Event Queue Backpressure — Blocking Put vs Oldest-Message-Drop

(ROB-002 / A2A-003)

### Reference Implementation (event_queue.py:46-62)

```python
async def enqueue_event(self, event: Event) -> None:
    async with self._lock:
        if self._is_closed:
            logger.warning('Queue is closed. Event will not be enqueued.')
            return

    logger.debug('Enqueuing event of type: %s', type(event))

    # Make sure to use put instead of put_nowait to avoid blocking the event loop.
    await self.queue.put(event)
    for child in self._children:
        await child.enqueue_event(event)
```

### Key Pattern

**A2A also uses blocking `await queue.put(event)`.** The SDK's `EventQueue`uses
a
bounded`asyncio.Queue(maxsize=max_queue_size)`(default 1024) and blocking put —
the exact same approach as our`EventAggregator._broadcast()`. The comment says
"use put instead of put_nowait to **avoid blocking the event loop**" — this is
misleading; `await queue.put()`will suspend the coroutine (not block the thread)
when the queue is full, effectively stalling the producer until space is
available.

The critical difference: A2A's`EventQueue`is **per-task** (one producer, one
consumer per SSE stream), while our`EventAggregator._broadcast()`iterates over
**all subscribers** sequentially. If subscriber B's queue is full, the`await
queue.put()`blocks delivery to subscriber C even though C has space.

A2A's per-task isolation is achieved via`InMemoryQueueManager`which creates
one`EventQueue`per task_id, and`tap()`creates independent child queues for
late-joining subscribers. Each consumer drains its own queue independently.

### What Our Code Should Do

1. **Keep bounded queues** (our`maxsize=512`is fine).
2. **Replace`await queue.put(event)`with`put_nowait()`+ drop-oldest on
   `QueueFull`** to prevent one slow client from stalling all broadcasts:

   ```python
   for client_id, queue in list(self._subscribers.items()):
       client_subs = self._subscriptions.get(client_id, set())
       if thread_id is None or thread_id in client_subs:
           try:
               queue.put_nowait(event)
           except asyncio.QueueFull:
               # Drop oldest event to make room (oldest-message-drop)
               try:
                   queue.get_nowait()
               except asyncio.QueueEmpty:
                   pass
               queue.put_nowait(event)
           delivered += 1
   ```

3. Alternatively, adopt A2A's per-task queue model with `tap()` for true
   isolation. This is a larger refactor but matches the canonical pattern.

---

## Issue 2: WebSocket permission_response Rejection (COMP-002)

### Reference Implementation

The A2A SDK does **not** use WebSocket for client commands at all. Its server
architecture is purely HTTP-based:

- **JSON-RPC endpoint** (`POST /`) handles all requests via `_handle_requests()`
  in `jsonrpc_app.py:298-410`.
- **SSE streaming** is used for async event delivery (not WebSocket).
- There is no WebSocket command handler to compare against.

The `JSONRPCApplication._handle_requests()`method validates the JSON-RPC method
name against`METHOD_TO_MODEL`(a dict mapping method strings to Pydantic models).
Unknown methods return`-32601 MethodNotFound`:

```python
model_class = self.METHOD_TO_MODEL.get(method)
if not model_class:
    return self._generate_error_response(
        request_id, A2AError(root=MethodNotFoundError())
    )
```

### Key Pattern (2)

A2A validates command types at the transport level and returns structured errors
for invalid operations. There is no silent swallowing.

### What Our Code Should Do (2)

In `websocket.py:268-277`, the `PERMISSION_RESPONSE` case currently silently
logs and drops. It should send an explicit error back to the client:

```python
case ClientCommandType.PERMISSION_RESPONSE:
    # ADR-011 §3.1: Permission responses MUST go through REST
    await websocket.send_json({
        "type": "error",
        "code": "INVALID_TRANSPORT",
        "message": "Permission responses must be submitted via REST endpoint "
                   "POST /api/threads/{thread_id}/permissions/{request_id}. "
                   "WebSocket delivery is not supported.",
    })
```

---

## Issue 3: Authentication — How A2A Handles It (SEC-006)

### Reference Implementation (auth/user.py:1-32, jsonrpc_app.py:110-160)

```python
# auth/user.py

class User(ABC):
    @property
    @abstractmethod
    def is_authenticated(self) -> bool: ...

    @property
    @abstractmethod
    def user_name(self) -> str: ...

class UnauthenticatedUser(User):
    @property
    def is_authenticated(self) -> bool:
        return False

    @property
    def user_name(self) -> str:
        return ''
```

```python
# jsonrpc_app.py — DefaultCallContextBuilder.build()

class DefaultCallContextBuilder(CallContextBuilder):
    def build(self, request: Request) -> ServerCallContext:
        user: A2AUser = UnauthenticatedUser()
        state = {}
        with contextlib.suppress(Exception):
            user = StarletteUserProxy(request.user)
            state['auth'] = request.auth
        state['headers'] = dict(request.headers)
        return ServerCallContext(
            user=user,
            state=state,
            requested_extensions=get_requested_extensions(
                request.headers.getlist(HTTP_EXTENSION_HEADER)
            ),
        )
```

### Key Pattern (3)

**A2A does NOT implement authentication itself.** It provides:

1. An abstract `User`/`UnauthenticatedUser` interface (`a2a.auth.user`).
2. A `ServerCallContext`that carries`user: User`and`state: dict`through
   every request.
3. A`CallContextBuilder`abstraction that consumers can override to inject
   their own auth logic.
4. A`DefaultCallContextBuilder`that tries to read`request.user`(set by
   Starlette's`AuthenticationMiddleware`) and falls back to
   `UnauthenticatedUser` if it's not available.

Authentication is **delegated to the deployer** via Starlette's standard
`AuthenticationMiddleware`. The SDK provides the plumbing (context propagation,
user abstraction) but no concrete auth backend (no API keys, no OAuth, no JWT
validation).

There is no `AuthenticationMiddleware`usage anywhere in the A2A SDK source
itself — it's expected to be added by the application that wraps the A2A app.

### What Our Code Should Do (3)

1. Create`src/vaultspec_a2a/api/auth.py`with a`User`ABC and`UnauthenticatedUser`class
   (matching A2A's pattern).
2. Add a`CallContext`or`RequestContext`that propagates user info through
   handlers.
3. For WebSocket: extract auth from the initial HTTP upgrade request headers.
4. For REST: use FastAPI`Depends()`with an auth dependency.
5. Initially, this can be a no-op (always`UnauthenticatedUser`) — but the
   plumbing must exist so auth can be plugged in later without refactoring
   every handler.

---

## Issue 4: anyio.create_task_group() in Lifespan (UNIMP-004)

### Reference Implementation (2)

**A2A does NOT use `anyio.create_task_group()` in its server lifespan.** The A2A
SDK has no lifespan handler at all in its FastAPI apps
(`A2AFastAPIApplication.build()`
and `A2ARESTFastAPIApplication.build()`both return a bare`FastAPI(**kwargs)`with
no lifespan parameter).

The SDK uses`asyncio.create_task()` for background work (e.g., in
`event_consumer.py:151-162`, agent tasks are monitored via `agent_task_callback`
registered on `asyncio.Task`).

The `pytest.mark.anyio` marker is used in tests, but that's for test runner
compatibility, not server architecture.

### Key Pattern (4)

A2A delegates lifespan management to the deployer. The SDK itself uses plain
`asyncio`primitives. There is no canonical`anyio.create_task_group()`pattern
in the reference.

### What Our Code Should Do (4)

If ADR-007 §5 specifies`anyio.create_task_group()`, that's a project-specific
decision (likely for structured concurrency benefits). The A2A SDK does NOT
validate this choice — it simply doesn't address lifespan. Options:

1. **Keep `asyncio.create_task()`** — matches A2A reference, simpler.
2. **Switch to `anyio.create_task_group()`** — follows ADR-007, provides
   automatic cleanup of background tasks on shutdown (structured concurrency).
   This is a better pattern for our use case where we need guaranteed cleanup.

If switching, the pattern would be:

```python
from contextlib import asynccontextmanager
import anyio

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with anyio.create_task_group() as tg:
        app.state.task_group = tg
        yield
    # All tasks in tg are guaranteed cancelled/finished here
```

---

## Issue 5: loop_count Increment Pattern in LangGraph (COMP-001 — CRITICAL)

### Reference Implementation (pregel/\_loop.py:1119-1120, 460-469, 811-813)

LangGraph uses a **step counter + stop limit** pattern at the graph execution
engine level, NOT at the node/state level:

```python
# _loop.py:1119-1120 — Initialization

self.step = self.checkpoint_metadata["step"] + 1
self.stop = self.step + self.config["recursion_limit"] + 1

# _loop.py:460-469 — Per-tick check

def tick(self, ...):
    # check if iteration limit is reached
    if self.step > self.stop:
        self.status = "out_of_steps"
        return False

# _loop.py:811-813 — After each tick

if not exiting:
    # increment step
    self.step += 1
```

```python
# pregel/main.py:2665-2674 — Error on exhaustion

if loop.status == "out_of_steps":
    msg = create_error_message(
        message=(
            f"Recursion limit of {config['recursion_limit']} reached "
            "without hitting a stop condition. You can increase the "
            "limit by setting the `recursion_limit` config key."
        ),
        error_code=ErrorCode.GRAPH_RECURSION_LIMIT,
    )
    raise GraphRecursionError(msg)
```

### LangGraph Example: User-Space Iteration Counter (code_assistant notebook)

For application-level loop control (like our `pipeline_loop`), the canonical
LangGraph example uses **explicit state field incremented by the node**:

```python
# State definition

class GraphState(TypedDict):
    error: str
    messages: Annotated[list[AnyMessage], add_messages]
    generation: str
    iterations: int  # <-- explicit counter in state

# Node increments counter

def generate(state: GraphState):
    iterations = state["iterations"]
    # ... do work ...
    iterations = iterations + 1  # <-- INCREMENT HERE, IN THE NODE
    return {"generation": code_solution, "messages": messages, "iterations": iterations}

# Router reads counter

max_iterations = 3
def decide_to_finish(state: GraphState):
    error = state["error"]
    iterations = state["iterations"]
    if error == "no" or iterations == max_iterations:
        return "end"
    else:
        return "generate"

# Initial invocation passes iterations=0

graph.stream({"messages": [("user", question)], "iterations": 0}, ...)
```

### Key Pattern (5)

LangGraph provides two loop-limiting mechanisms:

1. **Engine-level `recursion_limit`** (config parameter, default 25): Counts
   every graph step (node execution), incremented by the Pregel loop engine
   itself. Raises `GraphRecursionError`when exhausted. This is a safety net.

1. **Application-level state counter**: For domain-specific loop control (like
   "retry code generation at most 3 times"), the canonical pattern is to put an
   `iterations: int`field in the state, have the **looping node increment it**,
   and have the **routing function read it**.

**Our bug**:`_loop_router`reads`state.get("loop_count", 0)`but no node
ever writes`loop_count`back to state. The`loop_count`field in`TeamState`
is declared but never incremented by any node.

### What Our Code Should Do (5)

The loop node (or a wrapper around it) must increment `loop_count`in its
return value. Two approaches:

**Option A: Increment in`_loop_router`** (not recommended — routers should be
pure readers in LangGraph convention).

**Option B: Increment in the loop node wrapper** (matches LangGraph canonical
pattern):

```python
# In create_worker_node() or a pipeline_loop-specific wrapper:

async def loop_worker_node(state: TeamState) -> dict:
    result = await original_worker_node(state)
    result["loop_count"] = state.get("loop_count", 0) + 1
    return result
```

Also ensure the initial graph invocation passes `loop_count=0`or that the
default in`TeamState`is 0.

Additionally, consider setting`recursion_limit` in the graph config as a
safety net (LangGraph default is 25):

```python
config = {"recursion_limit": max_loops * len(pipeline_nodes) + 10}
```

---

## Issue 6: Subscriber Cleanup on Disconnect (A2A-001)

### Reference Implementation (event_queue.py:135-187, 193-244)

```python
async def close(self, immediate: bool = False) -> None:
    """Closes the queue for future push events and closes all child queues."""
    async with self._lock:
        if self._is_closed and not immediate:
            return
        if not self._is_closed:
            self._is_closed = True

    # Python 3.13+: queue.shutdown()
    if sys.version_info >= (3, 13):
        if immediate:
            self.queue.shutdown(True)
            await self.clear_events(True)
            for child in self._children:
                await child.close(True)
            return
        self.queue.shutdown(False)
        await asyncio.gather(
            self.queue.join(), *(child.close() for child in self._children)
        )
    else:
        if immediate:
            await self.clear_events(True)
            for child in self._children:
                await child.close(immediate)
            return
        await asyncio.gather(
            self.queue.join(), *(child.close() for child in self._children)
        )

async def clear_events(self, clear_child_queues: bool = True) -> None:
    """Clears all events from the queue without processing them."""
    cleared_count = 0
    async with self._lock:
        try:
            while True:
                event = self.queue.get_nowait()
                self.queue.task_done()
                cleared_count += 1
        except asyncio.QueueEmpty:
            pass
    if clear_child_queues and self._children:
        child_tasks = [
            asyncio.create_task(child.clear_events())
            for child in self._children
        ]
        await asyncio.gather(*child_tasks, return_exceptions=True)
```

```python
# InMemoryQueueManager.close() — in_memory_queue_manager.py:62-72

async def close(self, task_id: str) -> None:
    async with self._lock:
        if task_id not in self._task_queue:
            raise NoTaskQueue
        queue = self._task_queue.pop(task_id)  # Remove from registry
        await queue.close()                     # Then close
```

### Key Pattern (6)

A2A's cleanup is **two-phase**: (1) remove the queue from the manager's
registry, then (2) close/drain the queue itself. The `close()`method supports
both graceful (drain all events) and immediate (discard everything) modes.

The`EventConsumer.consume_all()`(event_consumer.py:85-149) also handles
cleanup: on receiving a final event, it calls`await self.queue.close(True)`
to immediately close and clear.

### What Our Code Should Do (6)

Our `remove_subscriber()`currently just does`dict.pop()`. It should also
drain the queue to prevent memory leaks:

```python
def remove_subscriber(self, client_id: str) -> None:
    queue = self._subscribers.pop(client_id, None)
    if queue is not None:
        # Drain remaining events to free memory
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
    self._subscriptions.pop(client_id, None)
```

---

## Issue 7: Fan-Out and Tap Pattern (A2A-002)

### Reference Implementation (event_queue.py:123-133, in_memory_queue_manager.py:51-85)

```python
# EventQueue.tap()

def tap(self) -> 'EventQueue':
    """Creates a child queue that receives all future events."""
    queue = EventQueue()
    self._children.append(queue)
    return queue
```

```python
# InMemoryQueueManager.create_or_tap()

async def create_or_tap(self, task_id: str) -> EventQueue:
    """Creates new queue if none exists, otherwise taps the existing one."""
    async with self._lock:
        if task_id not in self._task_queue:
            queue = EventQueue()
            self._task_queue[task_id] = queue
            return queue
        return self._task_queue[task_id].tap()
```

### Key Pattern (7)

`tap()`creates a **child queue** that receives all events enqueued to the
parent **from that point forward**. This solves the late-joining subscriber
problem:

1. First subscriber creates the task queue via`create_or_tap()`.
2. Late-joining subscribers get a child queue via `tap()`.
3. Each child has its own `asyncio.Queue`, so slow children don't block the
   parent or siblings.
4. `enqueue_event()`recursively pushes to all children. 5.`close()`recursively closes all children.

This does NOT solve the "missed historical events" problem —`tap()` only
delivers future events. For replay of missed events, A2A relies on the
`TaskResubscriptionRequest`JSON-RPC method, which fetches the current task
state and then creates a tapped child for future events.

### What Our Code Should Do (7)

For reconnection (client connects mid-stream):

1. Fetch current state snapshot via REST (existing pattern).
2. Subscribe to future events via WebSocket.
3. The`tap()`pattern from A2A could be adopted for per-thread fan-out
   instead of the current shared-subscriber-dict model.

---

## Issue 8: CORS and Security in A2A FastAPI Apps

### Reference Implementation (3)

**A2A does NOT configure CORS at all.** Neither`A2AFastAPIApplication` nor
`A2ARESTFastAPIApplication`add`CORSMiddleware`. The `build()`methods return
a bare`FastAPI()`or`A2AFastAPI()`with no middleware configuration.

A search across the entire A2A Python SDK repository for "cors",
"CORSMiddleware", or "allow_origins" returned **zero results**.

### Key Pattern (8)

CORS is considered an **application-level concern**, not a protocol concern.
The A2A SDK leaves it to the deployer to configure CORS based on their
deployment environment.

### What Our Code Should Do (8)

Our CORS configuration should be **restrictive by default**:

1. Do NOT use`allow_origins=["*"]`with`allow_credentials=True`(this is a
   security vulnerability — browsers will reject it anyway, but it signals
   intent to be wide-open).
2. Use environment-configurable origins:

```python
 app.add_middleware(
     CORSMiddleware,
     allow_origins=settings.cors_allowed_origins,  # default: ["http://localhost:5173"]
     allow_credentials=True,
     allow_methods=["GET", "POST"],
     allow_headers=["*"],
 )
```

1. For development, allow localhost origins. For production, restrict to the
   actual frontend domain.

---

## Summary of Findings

| Issue                      | A2A Pattern                                            | Our Gap                                                      | Severity     |
| -------------------------- | ------------------------------------------------------ | ------------------------------------------------------------ | ------------ |
| 1. Backpressure            | Blocking put (per-task isolation)                      | Blocking put (shared iteration) — one slow client blocks all | HIGH         |
| 2. Permission WS rejection | JSON-RPC method validation, structured errors          | Silent swallow                                               | MEDIUM       |
| 3. Authentication          | Abstract User + CallContext plumbing, no concrete impl | Zero auth plumbing                                           | MEDIUM       |
| 4. anyio task_group        | Not used in A2A (plain asyncio)                        | ADR says anyio, code uses asyncio                            | LOW          |
| 5. loop_count (CRITICAL)   | State field incremented by node, read by router        | Field exists but never incremented — **infinite loop**       | CRITICAL     |
| 6. Subscriber cleanup      | Two-phase: deregister then drain/close                 | Pop only, no drain                                           | MEDIUM       |
| 7. Tap/fan-out             | Per-task parent queue with child taps                  | Single shared subscriber dict                                | LOW (future) |
| 8. CORS                    | Not configured (deployer concern)                      | Should be restrictive                                        | LOW          |
