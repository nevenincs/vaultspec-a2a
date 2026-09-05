---
tags:
  - '#research'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:6e12cf642d4252a544a30380654fd6279f6bb4633842fe6012c511d1753e85b4'
related:
  - "[[2026-09-05-embedded-runtime-robustness-audit]]"
  - "[[2026-09-05-embedded-runtime-robustness-research]]"
  - "[[2026-08-02-control-action-leases-reference]]"
  - "[[2026-08-01-dashboard-bundled-runtime-consumer-record-correction-reference]]"
---

# `embedded-runtime-remediation` research: `remediation choices and implementation ownership`

The question is how to remediate the completed embedded-runtime audit without creating competing runtime designs or duplicate implementation queues. The evidence favors refinements to the existing decision owners, one release-qualification ADR, and one remediation plan that verifies active upstream work and implements the uncovered corrections. The measured baseline, ER01-ER28, and A01-A34 remain in the related audit and criteria research; they are not reproduced here.

## Findings

### The consumer contract must be qualified as an identified binary pair

The accepted dashboard-subordination decision already assigns authority to the consuming product. The owner's 2026-09-05 direction fixes this work's supplied shape as a Dashboard-embedded binary. Correcting the obsolete capsule-specific implementation prose preserves that authority; recreating a standalone product or changing Dashboard to tolerate arbitrary supplier output would change scope. ER23/ER24 and M18 in `2026-09-05-embedded-runtime-robustness-audit` identify the current-source mismatch and distinguish the older locked artifact. The evidence favors one pinned producer/consumer lifecycle contract and actual packaged-pair qualification over fixture-only conformance. Exact schema changes must be derived from the intended consumer generation, not invented in this research.

### Durable delivery fits the existing journal, but progress is not a receipt

The alternatives are an ordered drain of the existing durable journal, an in-memory queue, or an external broker. The first preserves one acceptance authority; an in-memory queue cannot meet crash recovery, while a broker adds a second acceptance/operations boundary without evidence that the existing store is insufficient. ER01/ER03 and `2026-08-02-control-action-leases-reference` favor action-specific checkpoint evidence and one renewable dispatcher with explicit queue admission limits. The completed leases plan is historical provenance, not an active implementation owner. Queue bounds are configuration established before testing, not tuned after observing overload. A graph-mutating action and a cancellation no-op have different evidence: the former incorporates input into checkpointed state, while the latter may concern work that never started. A universal checkpoint prerequisite would therefore strand a legitimate pre-dispatch cancellation. Cancellation needs an independent bounded control path; sharing execution capacity defeats the control operation intended to free it (ER04/ER05).

### Atomic lifecycle writes and bounded admission address distinct failure boundaries

ER02's stale-write and early-completion interleavings favor conditional state/revision election plus an independent durable terminal-delivery owner over cached ORM checks or a reader workaround. The state-truthfulness ADR was proposed at remediation orientation; acceptance belongs to its amended ADR, not an in-flight plan's wording. Its state obligations remain the design home. ER25 adds task-group cancellation cleanup to that ownership boundary.

ER28 demonstrates failed storage admission, not corruption or lost acknowledged work. The alternatives are bounded transactions with typed refusal, timeout-only tuning, or changing the storage backend. The evidence favors diagnosis and bounded refusal within existing SQLite ownership; neither a larger timeout nor a backend replacement is established as the remedy. `src/vaultspec_a2a/control/thread_service.py:479`, `src/vaultspec_a2a/database/_helpers.py:56`, and `src/vaultspec_a2a/control/dispatch.py:239` locate admission boundaries. The historical database-layer ADR primarily governs extraction and naming, so the leased-control decision is the narrower current admission owner.

### Full-input accounting and transactional prompt views preserve context ownership

Independent-message trimming, provider-only native compaction, and a validated replacement prompt view are the relevant options. ER07/ER08 favor budgeting the complete provider-visible input and retaining durable transcript authority while committing a validated prompt view. A summary is not assumed semantically faithful: seeded-fact continuation remains required by the audit criteria. Native compaction must be independently proven when claimed. The base provider/context ADR is the existing decision home; the newer ACP client-wire ADR and its open plan are specifically filesystem/terminal RPC work, not compaction or command implementation.

### Provider-native controls require explicit dispositions and actual effects

ER09/ER14 favor roster-bound recipient routing and session-scoped command support over treating target attribution as delivery or passing unknown command text as ordinary chat. Command-as-prompt is a valid negotiated mechanism; an arbitrary shell/RPC escape is not needed. Targeting belongs to the edge decision, provider-native command mechanics to the base provider decision, and Dashboard broker exposure remains an explicit integration dependency. Roster discovery already has active owners; routing is new work.

Codex uses a separate app-server client and chat-model implementation, including its request method and thread-start path (`src/vaultspec_a2a/providers/codex_chat_model.py:642`, :1015). ACP command implementation alone cannot establish the admitted Codex lane's control behavior. Its adapter needs separate mapping and effect proof; the presence of a generic request function is not a capability claim.

ER10/ER11 favor validating initialization before session use and settling every supplied stop outcome at the adapter boundary. ER12 favors extending existing condition preservation through setup and authentication, not adding another taxonomy. Known discriminator fidelity and genuinely unknown information must remain distinct. Existing SDK replacement stays probe-gated and is not a prerequisite imposed on these corrections.

### Resource control must distinguish saturation from dependency failure

ER26/ER27 favor capacity backpressure plus an atomically reserved recovery probe over opening a worker-wide failure circuit on ordinary saturation. Admission and provider failure classification are separate owners; the worker-breaker refinement belongs with control dispatch, not the provider taxonomy. ER15/ER16 favor cooperative server shutdown with one total drain deadline over Windows signal emulation and separately unbounded stream waits. These are refinements, not a new process architecture.

### Existing plans retain their implementation rows

The following current owners were read in full. The remediation plan can verify their outcomes and assign uncovered deltas, but must not create a second generic implementation row for the same work.

| Finding or coverage | Existing owner |
| --- | --- |
| ER13 capability composition and proof | `2026-08-02-provider-capability-evidence-plan` P01.S01-S02 and P02.S03-S04 |
| ER19 catalog availability test | `2026-08-02-provider-model-catalog-plan` P01.S11 |
| ER17/A07 provider-selection portion | Same catalog plan P03.S19-S20; packaged lifecycle/upgrade is additional scope |
| ER06 stream contract and assembled interaction proof | `2026-08-05-served-capability-contract-plan` W04.P09.S27 |
| State obligation/projection and abandoned-run semantics | Same served plan W04.P07.S22, W04.P08.S26 and W04.P08.S56 |
| Roster/structure prerequisites for ER09 | Same served plan W04.P08.S24 and W02.P04.S13 |
| Final client guide | Same served plan W03.P06.S47 and pre-existing W02.P03.S10 |

The fully checked leases, taxonomy and desktop plans remain historical records. New defects do not silently reopen their checkboxes. Active typing/decomposition work in repository-tooling-hardening must be coordinated when touching shared files; behavior-preserving cleanup does not own these runtime fixes. The audit retains evidence of test-profile, RAG identity, intermittent responsiveness and upstream warning problems (ER18-ER22); these require explicit plan rows without a new ADR per dependency.

### Qualification must retain the audit's evidence boundaries

Source regression, local deterministic execution, external provider work and Dashboard integration establish different facts. Source-only closure is cheap but insufficient for the missing boundaries; replacing the component is not warranted by the measured failure seams. The evidence favors adopting the frozen A01-A34 matrix as this campaign's qualification contract. Optional unsupported capabilities can be truthfully refused, but a required positive operation cannot pass by being disabled. Unavailable credentials or unsafe fault controls remain blocked evidence. The source paths and reproduction commands are retained in the audit; new implementation must re-ground at its actual revision.

## Sources

- `2026-09-05-embedded-runtime-robustness-audit` and `2026-09-05-embedded-runtime-robustness-research`.
- `2026-08-02-control-action-leases-reference`; `2026-08-01-dashboard-bundled-runtime-consumer-record-correction-reference`.
- `2026-08-02-control-action-leases-adr`; `2026-08-05-served-capability-contract-state-truthfulness-adr`; `2026-08-01-dashboard-bundled-runtime-subordination-adr`.
- `2026-07-14-a2a-edge-conformance-adr`; `2026-02-25-llm-context-provider-abstraction-adr`; `2026-08-02-provider-error-taxonomy-adr`; `2026-08-02-provider-capability-evidence-adr`.
- Existing owner plans named in the ownership table; `2026-08-02-llm-context-provider-abstraction-plan`.
- `src/vaultspec_a2a/control/thread_service.py:479`; `src/vaultspec_a2a/database/_helpers.py:56`; `src/vaultspec_a2a/control/dispatch.py:239`.
- A2A source `9438cf0bc1465a13892cb7fad197c44bd72c0360`; Dashboard comparison `330b2efe294c8ab134fff2142f9fae98afd14fec`; installed/locked versions recorded in the audit.

Additional control mapping locators: `src/vaultspec_a2a/providers/codex_chat_model.py:642`, :1015.
