---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:fad1d65179876c185902d4247515bd2b00cbe4152ef796d531bbd8ecf9f344d9'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` audit: `provider retry bounds implementation review`

## Scope

Reviewed condition-derived retry eligibility, real attempt counts, policy attachment, elapsed bounds, provider retry signals, partial output, and external-effect uncertainty for ACP and Codex turns.

## Findings

### provider-retry-bounds | high | A failed turn could replay after an external tool effect

Resolved. ACP tool/RPC activity and Codex action-item activity now mark the provider failure as effect-uncertain. The graph refuses a fresh model turn even when the supplied condition or lane hint would otherwise retry.

### provider-retry-bounds | medium | Retry elapsed behavior depended on LangGraph defaults

Resolved. All policy timing fields and attempt count are explicit. The production graph made three attempts with 1.5 seconds of configured delay and completed the focused test in 1.52 seconds inside a 3.0-second hard bound.

### provider-retry-bounds | medium | Supported wires do not supply a retry duration

Classified as a truthful information limit. ACP forwards no upstream retry header and Codex supplies only `willRetry`; the runtime uses its explicit bounded local schedule. No delay is parsed from provider prose or fabricated. Exact external-provider evidence remains in the qualification wave.

### provider-retry-bounds | medium | S87 compiler tests failed full-file type checking

Resolved during review. Two `CompiledTeamGraph` protocol accesses introduced by S87 now use explicit `Any` casts at the test-only visualization boundary. The recovery agent was notified for its S87 audit record.

### provider-retry-bounds | low | First bounded retry test failed before exercising backoff

Resolved. The test initially omitted its `asyncio` import and failed with `NameError`; the import was added and the failed invocation is not counted as evidence.

## Verification

- 19 focused retry, ACP effect, and Codex effect tests passed through the contained runner in 4.86 seconds.
- The real production backoff case observed 1.52 seconds for the frozen 1.5-second schedule.
- Ruff and Ty pass for every changed production and test file.

## Recommendations

- Keep policy timing explicit and review changes as runtime behavior changes.
- Reject retries whenever client output or external action activity makes replay uncertain.
- Do not claim provider-supplied delay support until a supported wire exposes a verified duration.
- Keep the broader A20 breaker, recovery, and failover result partial until its remaining owners close.
