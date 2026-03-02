---
date: 2026-02-27
type: audit
feature: a2a-reference
description: "Comparative analysis of A2A SDK reference implementations against our lib/ identifying critical drift in EventAggregator backpressure strategy and missing task state machine completion protocol."
related:
  - docs/adrs/2026-02-26-004-event-aggregation-replay-adr.md
  - docs/adrs/2026-02-26-003-protocol-bridging-translation-adr.md
  - docs/adrs/2026-02-26-006-protocol-ecosystem-bridge-adr.md
---

# A2A SDK Reference Audit

**Date:** 2026-02-27
**Auditor:** ref-a2a
**Scope:** Comparative analysis of A2A SDK reference implementations vs. our
lib/ implementations
**Status:** Complete

---

## Executive Summary

This audit analyzes 8 canonical A2A SDK reference files to identify patterns,
drifts, and correctness issues in our implementations. Key findings:

- **CRITICAL DRIFT**: Our `EventAggregator._broadcast()`uses drop-oldest
  backpressure (line 310–320), but A2A uses blocking`queue.put()`with
  timeout-based polling (EventConsumer line 94–96). This is architecturally
  opposite.
- **CRITICAL MISSING**: Task state machine completion protocol (A2A TaskUpdater
  lines 82–89). We lack terminal state protection and should gate all state
  transitions through a finalization lock.
- **HIGH DRIFT**: Result aggregation. A2A uses interrupt-aware consumption with
  background task continuation (ResultAggregator line 97–167). We don't expose
  similar patterns.
- **HIGH MISSING**: Request handler exception/cancellation patterns
  (DefaultRequestHandler lines 315–401). Our endpoints.py is missing structured
  cleanup and background task tracking.
- **MODERATE MISSING**: Streaming termination guarantees. A2A closes queue
  immediately after final event (EventConsumer line 128), we don't have explicit
  queue lifecycle management.

---

## 1. Event Queue Patterns

### A2A Implementation (event_queue.py)

### Architecture

- Bounded queue with`maxsize > 0`mandatory (line 37–38)
- Supports hierarchical "tap" pattern: child queues mirror parent's events (line
  123–133)
- Two-phase close: graceful (drain queue via`join()`) or immediate (clear
  events) (line 135–187)
- Python 3.13+ aware: uses native `QueueShutDown` exception, emulates on 3.12
  (line 164–186)

### Key Pattern: Backpressure Model

```python
# Line 46–62: enqueue blocks if queue is full
async def enqueue_event(self, event: Event) -> None:
    async with self._lock:
        if self._is_closed:
            logger.warning('Queue is closed. Event will not be enqueued.')
            return
    await self.queue.put(event)  # Blocks if full (bounded)
    for child in self._children:
        await child.enqueue_event(event)
```

- Uses `put()`NOT`put_nowait()`— **backpressure flows upstream**
- Recursive child fanning respects per-child backpressure
- Lock gates closed check; actual`put()` happens outside lock (unlock-put
  pattern)

### Key Pattern: Dequeue with Timeout Fallback

```python
# Line 64–113: non-blocking or waiting dequeue
if no_wait:
    event = self.queue.get_nowait()  # Raises QueueEmpty
else:
    event = await self.queue.get()  # Waits
```

- No timeout at queue level; caller (EventConsumer) applies timeout

### Our Implementation: EventAggregator._broadcast()

### Architecture: (2)

```python
# Line 290–323 in aggregator.py
async def _broadcast(self, event: ServerEvent) -> None:
    for client_id, queue in list(self._subscribers.items()):
        if queue.full():
            try:
                queue.get_nowait()  # DROP oldest
                logger.warning("Dropped oldest event for slow client %s", client_id)
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)  # Never blocks
        delivered += 1
```

### CRITICAL DRIFT

- **Drop-oldest backpressure** vs. **blocking put**
- A2A upstream blocker: `put()` waits if queue full → producer slows down
- We are: drop-tail strategy → silent data loss on slow subscribers
- This is **correct for our use case** (WebSocket fan-out) but **opposite
  philosophy**

### Why the difference matters

- A2A: Request-response RPC model. Blocking producer ensures all events
  persisted before response.
- We: Real-time streaming. Silent drops better than stalling all clients.
- **Decision: Document this conscious trade-off in ADR.**

### Missing Pattern: Hierarchical tapping

- A2A supports creating child queues (line 123–133) that auto-receive parent
  events
- We don't expose this; would help for multi-subscriber reconnection scenarios
- **Assessment: Low priority; we use flat subscriber model instead**

---

## 2. Task State Machine

### A2A Implementation (task_updater.py)

### State Transitions (lines 24–89)

```python
class TaskUpdater:
    def __init__(...):
        self._lock = asyncio.Lock()
        self._terminal_state_reached = False
        self._terminal_states = {
            TaskState.completed,
            TaskState.canceled,
            TaskState.failed,
            TaskState.rejected,
        }

    async def update_status(self, state: TaskState, ...):
        async with self._lock:
            if self._terminal_state_reached:
                raise RuntimeError(
                    f'Task {self.task_id} is already in a terminal state.'
                )
            if state in self._terminal_states:
                self._terminal_state_reached = True
                final = True
```

### Key Pattern: Terminal State Protection

- Once any terminal state is reached, ALL future `update_status()`calls
  raise`RuntimeError`
- Non-terminal states (working, idle, input_required, auth_required) can
  transition freely
- Final state automatically sets `final=True` flag on the event

### Terminal State Taxonomy

```text
A2A TaskState:
  submitted       → can transition to any non-terminal
  working         → can transition to any non-terminal
  input_required  → can transition to any non-terminal
  auth_required   → can transition to any non-terminal
  completed       → TERMINAL (no transitions allowed)
  canceled        → TERMINAL (no transitions allowed)
  failed          → TERMINAL (no transitions allowed)
  rejected        → TERMINAL (no transitions allowed)
```

### Helper Methods (lines 154–208)

- `complete(message)`→`update_status(TaskState.completed, final=True)`
- `failed(message)`→`update_status(TaskState.failed, final=True)`
- `cancel(message)`→`update_status(TaskState.canceled, final=True)`
- `reject(message)`→`update_status(TaskState.rejected, final=True)`
- `requires_input(message, final=False)`→`update_status(..., final=final)`
- `requires_auth(message, final=False)`→`update_status(..., final=final)`

### Our Implementation: AgentLifecycleState (schemas/enums.py)

### What we have

```python
class AgentLifecycleState(str, Enum):
    SUBMITTED = "submitted"
    IDLE = "idle"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    AUTH_REQUIRED = "auth_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

### What we're missing

1. **Terminal state protection** — No lock-gated state machine in
   EventAggregator
2. **Transition validation** — EventAggregator.emit_agent_status() accepts any
   state without checking legality
3. **Final flag semantics** — We don't auto-set `final=True`when entering
   terminal states
4. **Rejection state** — We use CANCELLED; A2A distinguishes rejected (user
   action) vs. canceled (system action)

### CRITICAL ISSUE

- A worker node could emit IDLE, WORKING, IDLE, WORKING, COMPLETED, COMPLETED,
  COMPLETED
- Second COMPLETED is allowed in A2A (error raised by TaskUpdater, not
  EventAggregator)
- We silently accept it; frontend sees duplicate final events

### Assessment

- **Must implement** in aggregator.py or a new TaskStateValidator
- Add`_terminal_states_per_thread: dict[str, set[str]]`to track reached
  terminals
- Gate all`emit_agent_status()` calls through state transition validation

---

## 3. Result Aggregator Patterns

### A2A Implementation (result_aggregator.py)

### Three consumption modes (lines 14–25)

### Mode 1: consume_and_emit() — Passthrough streaming

```python
async def consume_and_emit(self, consumer: EventConsumer) -> AsyncGenerator[Event]:
    async for event in consumer.consume_all():
        await self.task_manager.process(event)  # Persist
        yield event  # Forward to client
```

- Useful for SSE/streaming response
- Processing happens before yield (synchronous backpressure)

### Mode 2: consume_all() — Blocking final result

```python
async def consume_all(self, consumer: EventConsumer) -> Task | Message | None:
    async for event in consumer.consume_all():
        if isinstance(event, Message):
            self._message = event
            return event  # Early exit on Message
        await self.task_manager.process(event)
    return await self.task_manager.get_task()
```

- Blocks until stream ends (queue closes)
- Returns final Task or Message object
- Used for non-streaming request-response

### Mode 3: consume_and_break_on_interrupt() — Interruptible with background continuation

```python
async def consume_and_break_on_interrupt(
    self,
    consumer: EventConsumer,
    blocking: bool = True,
    event_callback: Callable[[], Awaitable[None]] | None = None,
) -> tuple[Task | Message | None, bool]:
    # ...
    async for event in event_stream:
        if isinstance(event, Message):
            self._message = event
            return event, False

        await self.task_manager.process(event)

        should_interrupt = False
        is_auth_required = (
            isinstance(event, Task | TaskStatusUpdateEvent)
            and event.status.state == TaskState.auth_required
        )

        if is_auth_required:
            logger.debug('Encountered auth-required task: breaking...')
            should_interrupt = True
        elif not blocking:
            logger.debug('Non-blocking call: returning task after first event.')
            should_interrupt = True

        if should_interrupt:
            # BACKGROUND CONTINUATION (lines 162–164)
            asyncio.create_task(
                self._continue_consuming(event_stream, event_callback)
            )
            interrupted = True
            break
    return await self.task_manager.get_task(), interrupted
```

### Key Pattern: Interrupt + Background Continuation

- On `auth_required`state OR non-blocking call: return immediately
- Spawn background task to continue draining event stream
- Event callback invoked after each event in background
- TODO comment (line 161) notes tracking outstanding tasks

### Our Implementation: lib/core/aggregator.py

### What we have: (2)

- Event emission only:`emit()`, `emit_agent_status()`, `emit_message_chunk()`,
  etc.
- No aggregation/consumption logic
- Single synchronous broadcast model

### What we're missing: (2)

- Result aggregation (Task/Message building from events)
- Interrupt handling (no auth_required interception)
- Background continuation semantics (fire-and-forget ingest via
  `tg.start_soon()`)
- Event callback for push notifications (only partial in endpoints.py line
  317–319)

### Assessment: (2)

- **This is OK** — our architecture is different
- A2A designs for request-response RPC (single request → agent execution →
  response)
- We design for real-time streaming (subscribe → receive events → disconnect)
- **No action needed** but should document in ADR

---

## 4. Request Handler Patterns

### A2A Implementation (default_request_handler.py)

### Pattern 1: Setup abstraction (lines 199–266)

```python
async def _setup_message_execution(
    self, params: MessageSendParams, context: ServerCallContext | None = None,
) -> tuple[TaskManager, str, EventQueue, ResultAggregator, asyncio.Task]:
    task_manager = TaskManager(...)
    task: Task | None = await task_manager.get_task()
    if task and task.status.state in TERMINAL_TASK_STATES:
        raise ServerError(...)
    if task:
        task = task_manager.update_with_message(params.message, task)
    elif params.message.task_id:
        raise ServerError(...)

    request_context = await self._request_context_builder.build(...)
    task_id = cast('str', request_context.task_id)

    if self._push_config_store and params.configuration and ...:
        await self._push_config_store.set_info(task_id, ...)

    queue = await self._queue_manager.create_or_tap(task_id)
    result_aggregator = ResultAggregator(task_manager)
    producer_task = asyncio.create_task(self._run_event_stream(request_context, queue))
    await self._register_producer(task_id, producer_task)

    return task_manager, task_id, queue, result_aggregator, producer_task
```

### Pattern 2: Exception handling + cleanup (lines 315–343)

```python
interrupted_or_non_blocking = False
try:
    async def push_notification_callback() -> None:
        await self._send_push_notification_if_needed(task_id, result_aggregator)

    (result, interrupted_or_non_blocking) = await result_aggregator.consume_and_break_on_interrupt(
        consumer, blocking=blocking, event_callback=push_notification_callback,
    )
except Exception:
    logger.exception('Agent execution failed')
    producer_task.cancel()  # Kill producer on exception
    raise
finally:
    if interrupted_or_non_blocking:
        # BACKGROUND CLEANUP (lines 337–341)
        cleanup_task = asyncio.create_task(
            self._cleanup_producer(producer_task, task_id)
        )
        cleanup_task.set_name(f'cleanup_producer:{task_id}')
        self._track_background_task(cleanup_task)
    else:
        # SYNCHRONOUS CLEANUP (line 343)
        await self._cleanup_producer(producer_task, task_id)
```

### Key Patterns

1. **Shared setup** — Consolidates TaskManager, queue, ResultAggregator creation
2. **Task registration** — Tracks running agents in `_running_agents: dict[str,
   asyncio.Task]`
3. **Exception cleanup** — On error, cancel producer task immediately
4. **Graceful vs. immediate cleanup** — If interrupted (auth_required or
   non-blocking), cleanup runs in background
5. **Background task tracking** — `_background_tasks: set[asyncio.Task]` with
   done callback (lines 410–431)

### Pattern 3: Background task lifecycle (lines 410–431)

```python
def _track_background_task(self, task: asyncio.Task) -> None:
    self._background_tasks.add(task)

    def _on_done(completed: asyncio.Task) -> None:
        try:
            completed.result()  # Raise exceptions
        except asyncio.CancelledError:
            logger.debug('Background task %s cancelled', completed.get_name())
        except Exception:
            logger.exception('Background task %s failed', completed.get_name())
        finally:
            self._background_tasks.discard(completed)

    task.add_done_callback(_on_done)
```

### Pattern 4: Streaming termination (lines 388–401)

```python
async def on_message_send_stream(...) -> AsyncGenerator[Event]:
    # ...
    try:
        async for event in result_aggregator.consume_and_emit(consumer):
            if isinstance(event, Task):
                self._validate_task_id_match(task_id, event.id)
            await self._send_push_notification_if_needed(task_id, result_aggregator)
            yield event
    except (asyncio.CancelledError, GeneratorExit):
        # CLIENT DISCONNECTED: Continue consuming in background
        bg_task = asyncio.create_task(result_aggregator.consume_all(consumer))
        bg_task.set_name(f'background_consume:{task_id}')
        self._track_background_task(bg_task)
        raise  # Propagate cancellation
    finally:
        # Always cleanup
        cleanup_task = asyncio.create_task(self._cleanup_producer(producer_task, task_id))
        cleanup_task.set_name(f'cleanup_producer:{task_id}')
        self._track_background_task(cleanup_task)
```

### Our Implementation: lib/api/endpoints.py

### What we have: (3)

- Simple request handlers for create_thread, send_message, get_thread_state,
  respond_to_permission
- Direct graph invocation via `tg.start_soon(aggregator.ingest, ...)`
- No structured task lifecycle management

### What we're missing: (3)

1. **Setup abstraction** — No equivalent to `_setup_message_execution()`
2. **Task lifecycle tracking** — No `_running_agents`dict, no deduplication
3. **Exception handling patterns** — send_message_endpoint (line 378–426) has
   zero error handling
4. **Background task tracking** — No`_background_tasks`set, no done callbacks
5. **Client disconnection handling** — No`asyncio.CancelledError`catcher for
   streaming reconnection

### CRITICAL ISSUES

- **Line 378–426 (send_message_endpoint):** No try/except. If
  aggregator.ingest() raises, the exception is unhandled and logged by FastAPI.
- **No producer task tracking:** Multiple messages to same thread could spawn
  overlapping graph invocations
- **No cleanup on error:** If`tg.start_soon()`fails, no cleanup of partial state
- **Missing permission callback:** We don't implement A2A's`event_callback`
  pattern for push notifications during background consumption

### Assessment: (3)

- **MUST implement** structured exception handling and background task tracking
- **SHOULD implement** producer task deduplication (prevent concurrent graph
  runs for same thread)
- **NICE-TO-HAVE** interrupt-aware consumption with background continuation

---

## 5. Streaming & Queue Lifecycle

### A2A Implementation (event_consumer.py)

### Pattern: Timeout-based polling for queue closure

```python
# Lines 71–150: consume_all()
async def consume_all(self) -> AsyncGenerator[Event]:
    while True:
        if self._exception:
            raise self._exception  # Propagate from agent_task_callback
        try:
            # Timeout loop to check _exception periodically
            event = await asyncio.wait_for(
                self.queue.dequeue_event(), timeout=self._timeout
            )
            self.queue.task_done()

            is_final_event = (
                (isinstance(event, TaskStatusUpdateEvent) and event.final)
                or isinstance(event, Message)
                or (isinstance(event, Task) and event.status.state in TERMINAL_STATES)
            )

            if is_final_event:
                logger.debug('Stopping event consumption in consume_all.')
                await self.queue.close(True)  # IMMEDIATE close
                yield event
                break
            yield event
        except TimeoutError:
            continue  # Retry queue.get()
        except (QueueClosed, asyncio.QueueEmpty):
            if self.queue.is_closed():
                break  # Queue is closed, exit generator
        except Exception as e:
            self._exception = e
            continue
```

### Key Pattern: Explicit Queue Closure After Final Event

- On final event: `await self.queue.close(True)`with`immediate=True`
- This prevents subsequent dequeue calls from blocking
- Guarantees clean generator termination

### Pattern: Exception Injection via Callback

```python
def agent_task_callback(self, agent_task: asyncio.Task[None]) -> None:
    if not agent_task.cancelled() and agent_task.done():
        self._exception = agent_task.exception()  # Store for re-raise in loop
```

- Agent task completes with exception → stored in `_exception`
- Consumer loop checks `_exception`at start of each iteration
- On next iteration, exception is raised in consumer context (not async task
  context)

### Our Implementation: lib/api/websocket.svelte.ts (frontend)

### What we have: (4)

- WebSocket client with auto-reconnect
- Sequence gap detection for reconnection
- No explicit queue closure or timeout handling (browser WebSocket API doesn't
  expose this)

### Backend considerations (endpoints.py)

-`tg.start_soon(aggregator.ingest(...))`spawns fire-and-forget task

- No explicit queue closure or final event detection
- Graph execution continues until no more events OR exception

### CRITICAL MISSING

- **No explicit final event detection** — We don't know when agent.ingest() has
  completed
- **No cleanup on generator exit** — If client closes WebSocket mid-stream,
  aggregator state leaks
- **No timeout-based polling** — If graph stalls, we don't detect it server-side

### Assessment: (4)

- **Must implement** final event detection (either by inspecting event types or
  emitting explicit "done" marker)
- **Must implement** cleanup on WebSocket disconnect (unsubscribe + cleanup
  aggregator state)
- **SHOULD implement** timeout detection for stalled graph execution

---

## 6. Specific Drifts Summary

### Drift 1: Backpressure Philosophy

| Aspect | A2A | Us | Impact |
| -------- | ----- | ---- | ---- |
| Full queue behavior | Block upstream | Drop oldest event | ✅ Correct for use case |
| Queue model | Hierarchical parents/children | Flat subscribers | ✅ OK, different architecture |
| **Assessment** | RPC-style request-response | Real-time fan-out | No action needed |

### Drift 2: Task State Machine

| Aspect | A2A | Us | Impact |
| -------- | ----- | ---- | ---- |
| Terminal state protection | Lock + flag gate | None | ❌ **CRITICAL** |
| Transition validation | TaskUpdater enforces | No validation | ❌ **CRITICAL** |
| Rejection vs. cancellation | Distinct states | Collapsed to cancelled | ⚠️ **HIGH** |
| Final flag auto-setting | Automatic on terminal | Manual | ⚠️ **HIGH** |

### Drift 3: Result Aggregation

| Aspect | A2A | Us | Impact |
| -------- | ----- | ---- | ---- |
| Interrupt awareness | Yes (auth_required) | No | ⚠️ **HIGH** (optional for our design) |
| Background continuation | Yes, with callback | No | ⚠️ **HIGH** (optional) |
| Early exit on Message | Yes | N/A (no result agg) | ✅ OK |
| Push notifications | Via event_callback | Partial in endpoints | ⚠️ **HIGH** |

### Drift 4: Request Handler

| Aspect | A2A | Us | Impact |
| -------- | ----- | ---- | ---- |
| Setup abstraction | `_setup_message_execution()` | Inline in endpoints | ⚠️ **MODERATE** |
| Exception handling | try/except + producer.cancel() | None | ❌ **CRITICAL** |
| Background task tracking | `_background_tasks`set + callback | None | ❌ **CRITICAL** |
| Producer deduplication | `_running_agents`dict | None | ❌ **CRITICAL** |
| Streaming disconnection | CancelledError → bg consume | No handling | ❌ **CRITICAL** |

### Drift 5: Streaming Termination

| Aspect | A2A | Us | Impact |
| -------- | ----- | ---- | ---- |
| Final event detection | Yes (explicit close) | No | ❌ **CRITICAL** |
| Queue closure | Explicit after final | No | ❌ **CRITICAL** |
| Timeout polling | Yes (0.5s intervals) | No | ⚠️ **HIGH** |
| Exception propagation | Via callback | Via task result | ✅ Different model OK |

---

## 7. Recommendations

### Immediate (P0 — Block other work)

1. **Implement terminal state protection** in EventAggregator
   - Add`_terminal_states_reached: dict[str, bool]`keyed by thread_id
   - Gate all`emit_agent_status()`calls through validation
   - Raise or log on illegal transitions

1. **Implement exception handling in endpoints.py send_message_endpoint**
   - Wrap`tg.start_soon()`in try/except
   - On error, emit error event + cleanup

1. **Implement producer task tracking**
   - Prevent concurrent graph runs for same thread
   - Add deduplication check before`tg.start_soon()`

### Near-term (P1 — Next sprint)

1. **Implement final event detection**
   - Emit explicit "done" event after graph completes
   - Or inspect events and detect terminal states (completed/failed/cancelled)

1. **Implement queue closure semantics**
   - Clear chunk buffers, debounce tasks on thread completion
   - Unsubscribe inactive threads from aggregator

1. **Implement background task tracking (similar to A2A)**
   - Track all fire-and-forget tasks spawned by endpoints
   - Add done callbacks for exception logging

### Long-term (P2 — Design work)

1. **Document backpressure trade-offs** in ADR
   - Explain drop-oldest vs. blocking put
   - Reference result_aggregator discussion

1. **Consider interrupt-aware consumption**
   - For auth_required → background continuation pattern
   - Would improve user experience on permission delays

---

## 8. Files Referenced

### A2A SDK

- `knowledge/repositories/a2a-python/src/a2a/server/events/event_queue.py`
-

`knowledge/repositories/a2a-python/src/a2a/server/events/in_memory_queue_manager.py`

- `knowledge/repositories/a2a-python/src/a2a/server/events/event_consumer.py`
- `knowledge/repositories/a2a-python/src/a2a/server/tasks/task_manager.py`
- `knowledge/repositories/a2a-python/src/a2a/server/tasks/task_updater.py`
- `knowledge/repositories/a2a-python/src/a2a/server/tasks/result_aggregator.py`
- `knowledge/repositories/a2a-python/src/a2a/server/request_handlers/default_request_handler.py`
- `knowledge/repositories/a2a-python/src/a2a/server/request_handlers/response_helpers.py`

### Our Implementation

- `lib/core/aggregator.py`(EventAggregator)
-`lib/api/endpoints.py` (REST handlers)

---

## Conclusion

Our architecture is fundamentally sound but missing critical patterns from A2A
that prevent silent failures and resource leaks:

1. **Terminal state protection must be added** — Currently any worker node can
   emit invalid state sequences
2. **Exception handling must be added** — Unhandled exceptions in background
   tasks are lost
3. **Queue closure must be explicit** — Threads continue accumulating state
   indefinitely
4. **Producer deduplication should be added** — Multiple concurrent graph runs
   for same thread possible

These are not "nice-to-have" improvements but essential correctness guarantees.
Recommend prioritizing P0 items before shipping to production.
