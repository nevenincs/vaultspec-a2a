---
tags:
  - '#adr'
  - '#acceptance-harness'
---

# `acceptance-harness` adr: `research_adr acceptance` | (**status:** `accepted`)

## Problem Statement

Prove the Research -> ADR contract end to end for `research_adr acceptance`.

## Decision

Adopt the deterministic acceptance harness as the standing proof that a prompt materializes exactly two governed documents on disk.

## Consequences

The harness is provider-agnostic; real providers are proven by the same driver against a live profile.
