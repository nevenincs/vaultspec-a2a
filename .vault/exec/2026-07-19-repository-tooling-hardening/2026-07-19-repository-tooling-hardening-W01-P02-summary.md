---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# `repository-tooling-hardening` `W01.P02` summary

- Modified: `just/dev/vault.just`
- Modified: `just/dev/rag.just`
- Modified: `src/vaultspec_a2a/cli/provision.py`
- Modified: `src/vaultspec_a2a/providers/_acp_mcp.py`
- Created: `scripts/vaultspec_core_enroll.py`
- Modified: focused production-behavior tests

## Description

W01.P02 added locked setup, installation, synchronization, upgrade, status, and
service verbs for Core and RAG. Workspace provisioning now requires Core from
the active locked environment, while ACP RAG acquisition and the installed RAG
CLI must match the same exact version authority. First-time Core adoption runs
destructively only in a disposable clone and promotes only byte-verified,
non-overwriting runtime state into the live workspace.
