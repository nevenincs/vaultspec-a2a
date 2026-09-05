---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:5819030e5c27669122409869adf6415bd3d22ea84d7266ee384c58db196cc353'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-qualification-inputs-reference]]"
  - "[[2026-09-05-embedded-runtime-robustness-audit]]"
---

# `embedded-runtime-remediation` audit: `rolling implementation review queue`

## Scope

This queue records findings surfaced while executing the approved embedded-runtime-remediation plan. Each entry retains severity, type, status, evidence, and owning follow-up. Historical ER01-ER28 evidence remains in the embedded-runtime-robustness audit.

## Findings

### qualification-pair-lock-drift | high | Dashboard does not select the captured A2A baseline

Type: contract and evidence gap. Status: open. At S01, the clean Dashboard checkout is `330b2efe294c8ab134fff2142f9fae98afd14fec`, but its component lock selects A2A `d59b41b6c1ac8b6e498326ea74ab32898ac9c08b` with release identity `0.1.0`. The clean A2A execution baseline is `0b94bf8636d7145ae9420adeb1af635ef81f9dd7`; its freshly built executable reports `0.3.0` and hashes to `B5F1DA8EDD6A6DC99C3FBD81645EFBA4BDF6646544B4140F4C51AE81E2EDF08F`. This is an exact identified incompatibility in the qualification pair, consistent with historical ER23/ER24. It blocks A27 and dependent Dashboard measurements, while independent local remediation continues. Ownership: `W01.P01.S02` records the coordinated consumer boundary, `W04.P10.S47-S50` conforms it, and `W05.P13.S64-S65` supplies closing proof.

### durable-message-capacity-absent | high | A10 has no declared queue capacity Q

Type: concurrency and durability. Status: open. Current source exposes bounded progress, ACP, stream-registry, and IPC buffers, but no atomic per-run or service capacity for durable follow-up messages. A Q+1 test cannot be defined without inventing a limit after observing results. This retains historical ER03 rather than weakening A10. Ownership: `W02.P04.S16-S18`; closing measurement: `W05.P11.S52`.

### frozen-binary-collects-test-modules | medium | The freeze closure analyzes and archives test packages

Type: packaging and operational risk. Status: open. The S01 freeze log analyzed the repository's acceptance, desktop, service, and unit-test packages because the PyInstaller specification calls `collect_all("vaultspec_a2a")`. The produced `PYZ-00.toc` contained 463 entries matching A2A test-package namespaces. The wheel's denylist does not constrain a PyInstaller build from the source checkout, so the current onedir closure can carry non-runtime test code and its dependency reach despite the declared pruned-runtime intent. The smoke checks still pass; this finding concerns release composition, size, and unnecessary code surface. Ownership: `W04.P10.S50` must correct or explicitly justify the actual frozen closure before `W05.P13.S65` certifies it.

## Recommendations

- Keep the captured A2A and Dashboard identities distinct until the Dashboard component lock, release manifest, discovery generation, and running process agree.
- Establish the durable message capacity before running A10; do not reuse an unrelated stream or IPC buffer as `Q`.
- Make the freeze recipe collect explicit runtime modules and data or exclude every test namespace, then inspect the built archive as part of the release lifecycle discriminator.
