---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:3922a6858e8c823582df3d19fce010dd787026def3bcbdeb9c934b88f3025d0d'
related: []
---
# `repository-tooling-hardening` audit: `Worker health public-contract review`

## Scope

Independent read-only review of the current S24 worker-health boundary: `WorkerHealthProbe`, the shared authenticated health probe, adoption and spawn provenance, watchdog state, health/service projection, gateway decode guards, and discovery JSON narrowing. The review covered the assigned worker, gateway, discovery, and live-regression tests.

## Findings

### strict-type-gate | medium | Assigned worker-health test scope still fails Basedpyright

Type: quality gate. Status: open. `uv run --no-sync basedpyright` over the seven assigned S24 files reports ten errors: private worker-helper use in the provenance and desktop decode tests, deprecated `Iterator` annotations on context managers, and missing `@override` annotations on HTTP handler overrides. Runtime evidence is green, but this tranche cannot satisfy its strict type-gate contract while the focused static command is red.

### nonobject-probe-coverage | low | No regression test exercises a 200 response with valid non-object JSON

Type: test coverage. Status: open. The implementation correctly narrows decoded health payloads through `TypeAdapter(dict[str, object])`, but the added tests cover malformed JSON and transport failure only. A real `200` response carrying a JSON scalar or array has a distinct parser path and should be pinned as healthy with `body=None`.

### unreadable-occupant-spawn-proof | low | The live malformed-body test does not drive the spawn refusal it documents

Type: test coverage. Status: open. `test_an_unreadable_worker_is_up_present_and_not_ours` proves the public probe and pairing refusal, but never calls the production spawn path. The claimed no-competitor invariant therefore remains indirectly inferred from control flow rather than being demonstrated against the same live malformed occupant.

## Recommendations

Repair the ten focused Basedpyright errors before closing S24, then rerun the exact focused command. Add real-loopback regressions for valid non-object 200 payloads and for a malformed healthy occupant reaching the production spawn path and producing neither adoption nor a competing spawn.
### strict-type-gate | medium | Closed: assigned worker-health strict gates now pass

Type: quality gate. Status: closed. Post-repair review ran `uv run --no-sync basedpyright` over all seven assigned S24 health files with 0 errors, `uv run --no-sync ty check` with all checks passed, and Ruff check plus format-check clean. The three live test modules collect and pass 12 tests.

### nonobject-probe-coverage | low | Closed: real array JSON remains a healthy bodyless probe

Type: test coverage. Status: closed. The real-loopback `200` probe test now returns `[]` - valid JSON but not an object - through both one-shot and pooled-client public paths. Both yield `WorkerHealthProbe(healthy=True, body=None)`, directly pinning the non-object decoder boundary.

### unreadable-occupant-spawn-proof | low | Closed: malformed healthy incumbent reaches public no-competing-spawn path

Type: test coverage. Status: closed. The real subprocess occupant serving malformed `200` JSON now drives public `LazyWorkerSpawner.ensure_worker()` with auto-spawn. The test confirms the same port still returns `200`, the spawner remains unspawned with no process handle, and a second public probe remains healthy/bodyless. This demonstrates retained-port refusal rather than inferring it from a private helper.

### authenticated-shutdown-proof | low | Authenticated-header assertion is vacuous under the current unarmed test configuration

Type: test coverage. Status: open. The retained foreign-worker test demonstrably calls the real loopback `/admin/shutdown`, retains the live port, and refuses a competing spawn. However this review confirmed `settings.internal_token is None` in the active test configuration, so the handler's `authenticated=True` condition succeeds without observing a bearer header. The no-competitor behavior is proved; a credential-configured real-loopback lane is still needed to prove bearer presentation during stale-worker eviction.

### authenticated-shutdown-proof | low | Closed: isolated subprocess proves both raw authentication variants

Type: test coverage. Status: closed. `test_subprocess_auto_spawn_sends_configured_shutdown_authorization` runs the public `LazyWorkerSpawner.ensure_worker()` and `probe_worker_health()` from a fresh interpreter with its temporary working directory isolating repository `.env` settings. Its real retained loopback incumbent records the exact raw `Authorization` header for tokenless and configured-token cases: respectively no header and `Bearer evict-secret`. In each case the incumbent remains healthy on the original port, `spawned` stays false, and no process handle is created. The test neither mutates the shared settings object nor relies on mocks, private helpers, casts, or `Any`.

## Recommendations

No open finding remains in this worker-health review scope. Retain the focused live loopback, Basedpyright, Ty, and Ruff checks as S24 regression evidence.
