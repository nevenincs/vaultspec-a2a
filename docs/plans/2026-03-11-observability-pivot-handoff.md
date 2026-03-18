# Observability Pivot Handoff

Date: 2026-03-11

## Status

Work is intentionally paused here on the previous backend-readiness execution
trail.

The current pivot is:

- stop treating the remaining work as only a Docker/provider verification issue
- treat observability architecture as the next first-class track
- preserve all existing audit/research state before continuing

## Why The Pivot Happened

The current codebase has real tracing and real Jaeger evidence, but the debug
story is still incomplete:

- traces and debug logs are not formally correlated
- Jaeger is being used as a trace evidence backend, but not as a complete
  debug-log authority
- Docker/container/ACP subprocess failures still do not produce one concerted
  diagnostic surface
- local ACP authority vs Dockerized provider runtime authority is not yet
  formalized by ADR/research-backed architecture

This means the remaining work is no longer just “finish provider verification”.
It is now also:

- define the authoritative observability model
- define the authoritative ACP runtime/observability boundary model

## Open Issues To Pick Up Next

Start with these tasks:

1. `#88` OBS-ARCH-01
   - Add formal log/trace correlation architecture and implementation for
     multi-service debugging
2. `#89` ACP-ARCH-01
   - Add ADR-backed authority model for local ACP vs Dockerized provider
     runtime and observability boundaries
3. `#87` PG-VERIFY-03
   - Prod-like Docker CLI verifier still times out at gateway readiness with
     too-thin startup diagnostics
4. `#86` PROV-DOCKER-02
   - Docker provider certification remains partial until live
     credential-backed verification is completed
5. `#71` AUDIT-LOOP-01
   - Keep the review/audit/queue sync rule active across every subsequent pass

## Required Reading Before Continuing

Read these first, in order:

1. `AGENTS.md`
2. `docs/research/2026-03-09-postgres-persistence-grounding.md`
3. `docs/audits/2026-03-08-continuous-backend-readiness-audit.md`
4. `docs/audits/2026-03-08-prod-readiness-consolidated-audit.md`
5. `docs/plans/2026-03-09-backend-readiness-execution-plan.md`
6. `docs/adrs/010-observability-telemetry-integration.md`
7. `docs/adrs/017-containerization-strategy.md`

Then inspect these code paths:

1. `src/vaultspec_a2a/utils/logging.py`
2. `src/vaultspec_a2a/telemetry/instrumentation.py`
3. `src/vaultspec_a2a/telemetry/middleware.py`
4. `src/vaultspec_a2a/cli/_verify.py`
5. `src/vaultspec_a2a/providers/factory.py`
6. `src/vaultspec_a2a/providers/probes/claude.py`
7. `src/vaultspec_a2a/providers/probes/gemini.py`

## Grounded Current Conclusions

### Logging and tracing

- Jaeger traces are working and remain mandatory.
- The repo already has real OTel trace propagation and Jaeger verification.
- Structured JSON logging exists, but log records do not yet carry OTel
  correlation identifiers by default.
- There is no ADR yet for log/trace correlation or for a single authoritative
  multi-service debugging surface.

### ACP authority

- Local ACP authority still works.
- Local Gemini ACP probe passed end to end on 2026-03-11.
- Local Claude ACP bridge also worked through `initialize` and `session/new`,
  but failed at `session/prompt` because the provider account hit its limit.
- This means the bridge is not currently broken; the failure was provider
  quota, not ACP handoff.
- Dockerized provider runtime was introduced to make the worker image
  self-sufficient and version-pinned for prod-like verification, not to replace
  the local ACP bridge. That still needs formal ADR-backed documentation.

### Production verifier

- The supported verifier surface now belongs to the CLI, not `scripts/`.
- `vaultspec test prodlike-docker` is the authoritative repo-owned verifier.
- A real run still failed with `gateway not ready after 120s`.
- Existing artifacts are better than before but still too thin to fully
  diagnose container startup stalls.

## Next Recommended Execution Order

1. Ground `#88` with official OpenTelemetry and Jaeger documentation.
2. Decide the observability model:
   - trace/log correlation fields only
   - or OTLP logs pipeline in addition
3. Capture that as research + ADR work before implementation.
4. Ground `#89` and formalize local ACP vs Docker runtime authority.
5. Only then return to `#87` and improve verifier diagnostics according to the
   chosen observability model.
6. Leave `#86` partial unless real provider credentials are available for live
   Docker certification.

## Mandatory Workflow Reminder

Every next slice must still do:

1. grounding/research
2. implementation
3. verification
4. code review
5. audit/research/queue sync

Do not treat “code written” as closure.
