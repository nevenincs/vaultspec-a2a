---
tags:
  - '#adr'
  - '#s05-deterministic-86bb85a9391b4eb5b911df58eda83d18'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:bafac2afa3ae5e9348e99fc75039e82fa4f4375be4c5bec1f00fe435af7c9195'
related:
  - "[[2026-08-02-s05-deterministic-86bb85a9391b4eb5b911df58eda83d18-research]]"
---

# `acceptance-harness` adr: `research_adr acceptance` | (**status:** `accepted`)

## Problem Statement

Prove the Research -> ADR contract end to end for `research_adr acceptance`.

## Decision

Adopt the deterministic acceptance harness as the standing proof that a prompt materializes exactly two governed documents on disk.

## Consequences

The harness is provider-agnostic; real providers are proven by the same driver against a live profile.
