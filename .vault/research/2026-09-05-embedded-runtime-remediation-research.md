---
tags:
  - '#research'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:37096b46081e3de86c1e659a81f5ac12f442bfa8bf5290e9d4f5cc1b310c2bed'
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

## W01.P02.S07 loop-gap and cold-catalog diagnosis

The production compile path at current HEAD retains the same required mechanism inspected at the original audit baseline: `GraphLifecycleManager._compile_graph` awaits `asyncio.to_thread(warm_model_imports)` before synchronous provider construction, while worker startup also starts a background offloaded warmup. Fresh separation on the named Windows 10 Pro / Ryzen 9 5900X / locked Python 3.13.11 host measured an on-loop import at 3.5687 seconds with a 3.5688-second gap, the same imports offloaded at 2.8176 seconds with a 0.0851-second gap, and one production compile at 1.5716 seconds with a 0.0552-second gap. This proves both that the meter detects the cold stall and that the current offload prevents it; it does not erase ER21's original 25.312691-second work / 0.6182457-second gap or the unchanged M15 pass.

The repeatability gate now establishes a named load rather than inheriting incidental machine contention. Five owned base-interpreter processes represent the campaign's frozen worker capacity `C=5`; each must accrue CPU before the measurement and throughout five fresh cold production compile subprocesses. An idle event-loop subprocess runs under the same load first and must remain below the unchanged 0.5-second ceiling, otherwise the measurement fails as inconclusive due to scheduler starvation. The final capture measured idle at 0.0191561 seconds, compile gaps 0.0464355, 0.0701506, 0.0609854, 0.0792614 and 0.0816821 seconds, compile work 2.2656-2.8778 seconds, and 43.34-48.55 CPU seconds for every load owner. The owning warmup path therefore needs no production correction.

The first load-harness run failed before compile measurement because Windows virtual-environment `python.exe` is an idle redirector whose child is the executing interpreter. Measuring the redirector reported zero CPU and correctly refused the run as vacuous. The corrected harness launches the current base interpreter directly, keeps its exact process identities, verifies real CPU accrual, and reaps them in `finally`; a process scan after the failed diagnostic found no owned burner. This is a measurement-harness finding resolved inside S07, not evidence of a warmup failure.

The separately reassigned provider-catalog/Uvicorn observation has no demonstrated warmup coupling. The exact current-schema production restart test passed once in 21.42 seconds and then five fresh repetitions in 17.10-19.03 pytest seconds (20.56-23.61 wall seconds), with no shutdown failure. The pre-review combined exact-source run passed the warmup module and restart case, five tests in 89.00 seconds; the loaded compile case took 52.90 seconds and the restart case took 16.65 seconds. The historical 91.79-second cold discovery included an external Claude timeout, while process-tree and graceful gateway shutdown remain lifecycle concerns. S07 records the non-reproduction and leaves the runtime lifecycle finding open under `W04.P10.S49`; it does not claim to close it.

## W01.P02.S07 exact timing-boundary correction

Formal review found the initial compile result mixed two intervals: graph duration ended immediately after `get_or_compile_graph`, but the heartbeat remained live through bridge close and checkpointer exit. The reproduced 2.3452-second work / 11.0947-second gap pair proved that mismatch. The corrected meter owns one shared last-tick timestamp and freezes the partial final heartbeat interval synchronously at the exact timestamp used to end each duration. It resets before measuring bridge close, checkpointer exit and a post-cleanup ambient scheduler tail separately.

This separation changed the diagnosis. Under the same non-vacuous five-owner load, all five compile gaps passed the unchanged 0.5-second ceiling at 0.0546-0.1796 seconds. One independent bridge-close phase took 7.1849 seconds and blocked the loop for 3.6920 seconds; its sibling bridge samples stayed at 0.0272-0.0769 seconds, while checkpointer exit and ambient scheduling stayed below 0.018 seconds. The bridge path was real: graph compilation buffered an event and close exhausted asynchronous delivery retries against the unreachable test gateway. The finding therefore belongs to worker/gateway shutdown qualification `W04.P10.S49`. S07 retains the phase evidence and does not treat that lifecycle threshold as passed.

The corrected warmup module passed five tests in 139.74 seconds. Its stable assertions cover exact compile-window responsiveness and non-vacuous phase separation; they do not waive the open S49 defect. The current-schema restart/catalog path separately passed in 51.63 seconds, with no shutdown failure despite its 50.79-second cold call.
