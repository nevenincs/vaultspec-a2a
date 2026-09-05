---
tags:
  - '#reference'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:ca9e5f4d3cff13591f232b448a9731f45fc12143ef8a35e601319b1aff96089c'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
  - "[[2026-09-05-embedded-runtime-robustness-research]]"
  - "[[2026-09-05-embedded-runtime-robustness-audit]]"
---

# `embedded-runtime-remediation` reference: `qualification-inputs`

## Summary

This record freezes the inputs for plan Step `W01.P01.S01`. It records the execution baseline before behavioral remediation. Later qualification must replace the baseline commit and binary hash with the exact corrected artifacts it tests; doing so does not change any A01-A34 acceptance threshold.

## Identity baseline

| Item | Frozen S01 value | Qualification meaning |
| --- | --- | --- |
| A2A repository commit | `0b94bf8636d7145ae9420adeb1af635ef81f9dd7` | Clean tracked checkout used for this evidence capture and fresh binary build. |
| A2A release identity | `vaultspec-a2a 0.3.0` | Reported by the freshly built executable and locked environment. |
| Fresh S01 executable | `tmp/embedded-runtime-remediation-s01-binary/vaultspec-a2a/vaultspec-a2a.exe` | Local qualification-input artifact built by the repository freeze recipe; ignored and not a release asset. |
| Fresh executable SHA-256 | `B5F1DA8EDD6A6DC99C3FBD81645EFBA4BDF6646544B4140F4C51AE81E2EDF08F` | Exact binary identity for S01 evidence only. |
| Fresh onedir extent | executable `30,533,532` bytes; `2,128` files; `141,715,717` total bytes | Records the built closure before later packaged-pair qualification. |
| Freeze command | `uv run --locked --group freeze python scripts/build_binary.py --dist tmp/embedded-runtime-remediation-s01-binary` | Completed successfully, including version, help, and disallowed `run-module os` smoke checks. |
| Earlier audit executable | SHA-256 `EDE9B961F7D52952FD1522DB23295AE810490D01C029ADEF869C37EB6354E688`; version `0.3.0`; `30,533,532` bytes | Retained as historical pass-two evidence from source baseline `9438cf0bc1465a13892cb7fad197c44bd72c0360`; it is not substituted for the fresh S01 artifact. |
| Dashboard checkout generation | `330b2efe294c8ab134fff2142f9fae98afd14fec` | Current clean tracked intended consumer checkout at capture time. |
| Dashboard component lock | A2A commit `d59b41b6c1ac8b6e498326ea74ab32898ac9c08b`, release `vaultspec-a2a 0.1.0` | The current product generation does not select the S01 A2A baseline. `W01.P01.S02` owns the coordinated contract boundary; `W04.P10` owns lifecycle conformance; `W05.P13` owns packaged-pair proof. |

The intended qualification pair is therefore identified but not yet composable: A2A work starts from commit `0b94bf8...`, while Dashboard generation `330b2ef...` still pins a different A2A source and release identity. No Dashboard result may be attributed to the fresh S01 executable until the lock, generated release files, manifest digests, discovery generation, and launched process identity all agree.

## Host and locked toolchain

The named host is Windows kernel `10.0.26200`, x64, reported product label `Windows 10 Pro`, AMD Ryzen 9 5900X with 12 cores and 24 logical processors, and `137,346,269,184` bytes of physical memory. The project-locked Python is `3.13.11`; ambient `python` resolves to `3.14.7` and is excluded from certification commands.

Resolved locked versions are Vaultspec Core `0.1.73`, LangGraph `1.2.11`, HTTPX `0.28.1`, pytest `9.1.1`, PyInstaller `6.22.2`, Uvicorn `0.52.4`, and uv `0.12.8`. Provider executables observed on this host are Codex CLI `0.153.2`, Claude Code `2.1.261`, Gemini CLI `0.58.0`, Kimi `0.36.1`, and Node `26.8.1`. Executable presence and a version response are inventory facts only; neither is completed-work proof.

## Supported-mode inventory

The inventory comes from `ProviderFactory.catalog_registrations(..., serve_in_process_lanes=False)` and the exact-key admission gate. These are the complete external catalog registrations at the frozen commit.

| Provider/mode | Served disposition | Current evidence statement |
| --- | --- | --- |
| `antigravity/antigravity-cli` | blocked | No exact-mode completed-turn proof. |
| `claude/claude-agent-acp:node` | blocked | Provider-level history does not transfer to this catalog execution mode. |
| `codex/codex-app-server` | selectable | The exact catalog key is admitted by the recorded completed-turn declaration. Later W05 proof must rerun three real turns through the intended Dashboard/binary pair. |
| `gemini/gemini-cli-acp` | blocked | No exact-mode completed-turn proof. |
| `kimi/kimi-code-acp` | blocked | Handshake or executable availability is not a completed turn. |
| `openai/openai-api` | blocked | No exact-mode completed-turn proof. |
| `zai/zai-claude-agent-acp:node` | blocked | Provider-level history does not transfer to this catalog execution mode. |
| `zhipu/zhipu-openai-compatible-api` | blocked | No exact-mode completed-turn proof. |

The mock and deterministic modes are explicit in-process certification lanes. They are excluded from this external inventory and cannot establish provider or packaged-consumer success.

## Frozen pre-test limits

| Boundary | Frozen value or formula | Required use |
| --- | --- | --- |
| Durable follow-up-message queue `Q` | No declared atomic per-run or service capacity exists at S01. | A10 remains blocked until `W02.P04.S16` establishes `Q`; then test exactly `Q` plus `Q+1`. This absence does not relax the criterion. |
| Worker execution concurrency `C` | `max_concurrent_threads = 5` | A28 runs 30 minutes at five occupied executions and separately at ten submitted executions. |
| Progress subscriber queue | `event_queue_maxsize = 512` per subscriber | A22 must force overflow and require an explicit gap/resynchronization outcome. |
| Stream registry | `max_stream_connections = 256`; `max_subscriptions_per_client = 512` | A28 reports peak bounded connections and subscriptions. |
| ACP chunk queue | `acp_chunk_queue_maxsize = 1,024` per session | Provider stream load must not silently lose terminal meaning. |
| Worker IPC event buffer | `ipc_max_event_buffer = 10,000`, currently drop-oldest; flush `0.05s`, three retries, `0.1s` exponential base | A22/A26 must distinguish delivery loss or overflow from authoritative state. |
| Input and IPC bounds | internal frame/body `1,048,576` bytes each; context limit `120,000` estimated tokens; mount ceiling `20,000` tokens | A16 samples 80%, 95%, and above the declared context limit without changing units after results. |
| Database admission | SQLite busy timeout `5,000ms`; pool `5` plus `10` overflow | A25 and A28 record contention and connection peaks on disposable stores. |
| Graph stall deadline `B` | `max(90s, run step_timeout_seconds + 30s)` | A24 permits valid silence through the run's own budget and requires a true stall to resolve by `B` plus one observation/poll interval. |
| ACP turn idle deadline | `600s`, reset by protocol activity | A24/provider drills distinguish a long active turn from silence. |
| Provider call timeout | `120s`; ACP startup `300s`; ACP management RPC `15s`; interactive auth `900s` | A19/A20 record which bound actually fired and preserve the supplied condition. |
| Worker liveness | heartbeat stale after `90s`; watchdog poll `5s`; breaker opens after three failures and probes after `30s` | A21/A24 report detection time separately from the frozen five-second post-detection visibility target. |
| Worker startup | `30s`, poll from `0.1s` to `2s` | A26/A27 record startup and replacement identity. |
| Gateway drain | current application quiescence wait `5s` | A26 measures one total lifecycle deadline after remediation; the current five-second inner wait is an observed input, not proof of total bounded shutdown. |
| Dashboard resident discovery | heartbeat stale after `120s`; health probe timeout `1.5s` | A21 records detection and projection separately. |
| Gateway/control endpoints | gateway `127.0.0.1:18000`; worker `127.0.0.1:18001`; MCP `0.0.0.0:8200` with loopback Host/Origin defaults | A04/A21 name the tested endpoint and isolation configuration. |

The frozen campaign sample sizes remain: A03 uses 20 simultaneous callers; A09 uses 100 distinct messages plus 20 identical retries; A14 and A18 use 10 repeats at each named boundary; A28 uses 30 minutes for each load shape; A29 uses at least 100 samples separately for status, message, and cancel acknowledgements with p95 at most one second and p99 at most three seconds. A21 retains five seconds after detection. Post-quiescence A28 RSS growth remains bounded by the greater of ten percent of baseline and 50 MiB.

## A01-A34 applicability

All 34 campaign criteria apply to the embedded-runtime qualification. The qualification column identifies boundaries or conditional subcases; a missing prerequisite is `BLOCKED`, not non-applicable.

| Criterion | Applicability | Qualification boundary or condition |
| --- | --- | --- |
| A01 | applicable | Source plus intended Dashboard/package pair. |
| A02 | applicable | Local durable stores plus Dashboard CRUD. |
| A03 | applicable | Local 20-caller admission race. |
| A04 | applicable | Local and Dashboard auth, generation, and workspace isolation. |
| A05 | applicable | Complete mode inventory; provider boundary for every selectable external lane. |
| A06 | applicable | Exact lane/model/capability agreement; no sibling proof transfer. |
| A07 | applicable | Three real turns for each admitted external lane; currently Codex is the sole selectable catalog lane. |
| A08 | applicable | Durable message acceptance locally and through Dashboard. |
| A09 | applicable | Local ordering and replay drill. |
| A10 | applicable, currently blocked | The absent durable queue `Q` is owned by S16. |
| A11 | applicable | Typed clarification locally, on admitted real lanes, and through Dashboard. |
| A12 | applicable | Permission decisions locally and on each claiming provider lane. |
| A13 | applicable | Cancellation races locally, on applicable real lanes, and through Dashboard. |
| A14 | applicable | Local crash-boundary recovery, 10 repeats each. |
| A15 | applicable | Positive command effects for advertised commands; truthful refusal for genuinely unsupported commands. |
| A16 | applicable | Actual assembled provider input at 80%, 95%, and above limit. |
| A17 | applicable by lane claim | Every lane claiming compaction needs real effect proof; unsupported lanes must refuse truthfully. |
| A18 | applicable | Compaction races, 10 repeats each; provider subcase only on a lane executing compaction. |
| A19 | applicable | Local faults plus safely reachable exact-provider faults; inaccessible provider faults remain blocked. |
| A20 | applicable | Retry/breaker/failover locally and on safely testable real-provider conditions. |
| A21 | applicable | Provider, worker, stream, database, and engine discovery independently degraded. |
| A22 | applicable | Snapshot, disconnect, overflow, stale cursor, and reload. |
| A23 | applicable | Source ownership audit plus local state interleavings. |
| A24 | applicable | Run-derived local deadline and real-provider long-work case. |
| A25 | applicable | Disposable store crash, locking, disk-full, and read-only cases. |
| A26 | applicable | Local and Dashboard-owned drain, replacement, and child census. |
| A27 | applicable, currently blocked | Requires a component lock and Dashboard generation selecting the tested binary. |
| A28 | applicable | Local and Dashboard/package sustained load at `C` and `2C`. |
| A29 | applicable | Named host/load; 100 samples per operation. |
| A30 | applicable | Local and Dashboard diagnostics/log retention with canaries and UTF-8 bounds. |
| A31 | applicable | Addressed messaging always; provider subagent/background subcases only where separately claimed. |
| A32 | applicable | Every measurement must retain exact command, identity, boundary, exclusions, and queue update. |
| A33 | applicable | Negotiated protocol lanes; absent optional capability must refuse without authorization. |
| A34 | applicable | Every provider lane that supplies a stop outcome; coarser/unknown only when the transport supplies no finer fact. |

## Evidence exclusions and ownership

No source test, mock or deterministic lane, skipped test, handshake, executable version response, catalog enumeration, or helper-only binary smoke substitutes for required external-provider or Dashboard evidence. The Dashboard lock mismatch and absent message `Q` are tracked gaps, not permission blockers. Their owners are `W01.P01.S02`/`W04.P10`/`W05.P13` and `W02.P04.S16`/`W05.P11.S52`, respectively.
