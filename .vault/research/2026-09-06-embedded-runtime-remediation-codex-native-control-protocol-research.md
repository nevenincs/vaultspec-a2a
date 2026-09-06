---
tags:
  - '#research'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:40ba655579800e93d0a61dc7772f555e0635eaf808643e291539816e1efff1ae'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-06-embedded-runtime-remediation-codex-native-control-review-audit]]"
---
# `embedded-runtime-remediation` research: `Codex native control protocol and effect evidence`

The question was whether the admitted Codex app-server lane exposes controls whose completion and target can be represented truthfully by the A2A provider boundary. Current protocol documentation and the repository's session lifecycle support exact-turn interruption. They do not support a durable compaction claim in the current architecture.

## Findings

### Interruption requires both thread and turn identity

The documented `turn/interrupt` request takes `threadId` and `turnId`, returns an empty result immediately, and later settles the targeted turn through `turn/completed` with status `interrupted`. Therefore an empty result proves request acknowledgement only. A truthful completed outcome needs the matching terminal notification, and a bounded provider must report failure with effect uncertainty when that notification is absent or carries another status.

The repository obtains the thread identity from `thread/start` and the turn identity from `turn/start` inside one owned app-server client at `src/vaultspec_a2a/providers/codex_chat_model.py`. Those exact identities provide the narrow authority needed for interruption without a caller-selected generic RPC surface.

### Manual compaction is asynchronous and its effect belongs to a persistent thread

The documented `thread/compact/start` request returns immediately and reports progress through context-compaction item notifications. The useful state change belongs to the addressed Codex thread. The repository currently creates a fresh app-server thread for every model generation and destroys its temporary Codex home afterward. It therefore has no persistent thread authority against which the Dashboard could observe durable reduced context, released tokens, or later-turn reuse.

An RPC acknowledgement or a compaction progress item would be insufficient effect evidence. Qualification would need a persistent owned thread, observable pre/post context state, and proof that a later turn consumes the compacted state.

### Arbitrary RPC exposure is unnecessary

The verified control has a fixed method and a fixed structured argument shape. Exposing a generic method name or free-form parameter object would add authority without enabling any admitted behavior. The evidence favors a literal interruption operation and explicit unsupported refusal for every other control until its target and effects are independently proven.

## Sources

https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md

`src/vaultspec_a2a/providers/codex_chat_model.py`
`src/vaultspec_a2a/providers/tests/test_codex_chat_model.py`
