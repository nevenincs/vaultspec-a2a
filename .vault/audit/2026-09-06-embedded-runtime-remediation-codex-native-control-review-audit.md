---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:996ac4fb438c17a934058bf18252f2a2cf7588c8874d80e890c20672197edaff'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` audit: `Codex native control implementation review`

## Scope

Reviewed W03.P08.S81 against the admitted Codex app-server protocol, exact active-turn authority, bounded completion evidence, concurrent ownership, absent-control refusal, and the prohibition on exposing a generic RPC method.

## Findings

### codex-interrupt-acknowledgement | high | An empty RPC response could be mistaken for completed interruption

Resolved. The empty `turn/interrupt` result is treated only as request acknowledgement. The provider waits within the same ten-second total deadline for the exact registered turn to emit terminal status `interrupted`. A different terminal status or a missing terminal notification returns failed with effect uncertainty.

### codex-active-turn-authority | high | Native control could target an unrelated or stale Codex turn

Resolved. The model registers only the exact `thread/start` and `turn/start` identities owned by its live app-server client, removes that pair on stream exit, refuses absent and already-terminal pairs, and sends both exact identities in the structured interrupt request.

### codex-control-escape | high | A generic JSON-RPC entry point could bypass admitted controls

Resolved. The public method admits only literal `interrupt`; every other name is unsupported. Runtime identities are bounded printable exact strings, and callers cannot supply an RPC method or arbitrary parameter object.

### codex-interrupt-concurrency | medium | Duplicate interrupt calls could race on one active turn

Resolved. One call elects in-flight ownership before awaiting the app server. A duplicate receives busy, and ownership is released in `finally` for completion, failure, timeout, protocol error, or caller cancellation.

### codex-compaction-effect | high | Ephemeral Codex threads cannot substantiate durable context compaction

Blocked by design and queued under W04.P09.S45 plus W05 qualification. The provider refuses `compact` as unsupported. It does not advertise context reduction, token release, or durable compacted state from `thread/compact/start` because every generation currently owns a fresh ephemeral Codex thread.

### codex-native-control-consumer | medium | Provider control is not yet reachable through the shipped Dashboard contract

Open under W04.P09.S42 and W04.P09.S45. S81 establishes the provider boundary; the broker and CRUD surface still require exact target routing and honest outcome propagation.

## Recommendations

- Keep Codex interruption bound to the exact active thread and turn pair.
- Preserve terminal-event proof before returning completed.
- Keep compaction unavailable until persistent context authority and measurable state effects exist.
- Carry blocked, busy, failed, unsupported, and effect-uncertain outcomes unchanged through W04.P09.
