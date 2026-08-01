---
tags:
  - '#reference'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:009a2a600757b0409784c4142b31a6ea60f6af6fbb55410df5d722077098ba79'
related:
  - "[[2026-07-19-repository-tooling-hardening-reference]]"
  - "[[2026-07-19-repository-tooling-hardening-adr]]"
---
# `strict-quality-gates` reference: `Core and RAG quality-harness contracts`

## Summary

A2A already has the preferred Core-style architecture: `justfile` is a thin facade, while `dev/toolchain.py` is the source of truth for targets, process invocation, gating, advisory semantics, and target composition. The reusable implementation is not a copied Justfile; it is the explicit target registry and separate CI steps that preserve one result per dimension.

### Reusable strict-type contract

Core has a fast Ty target and a separate Basedpyright strict target. Its CI runs strict typing independently and blocks on the result after the tree has reached zero. A2A has the same pair in `dev/toolchain.py`, with strict mode configured in `pyproject.toml:345-375`; its CI aggregate currently includes Ty but not Basedpyright. For A2A, cross-platform Ty should be added as a first-class target before requiring it in CI because desktop code is platform-sensitive. Configuration exceptions, including Core's test-specific private-use treatment, must not be copied without an A2A-local census and concrete white-box need.

### Reusable complexity contract

Core treats cognitive complexity, nesting, and design size as named, independently reported CI gates. RAG keeps the same named local commands but makes unfinished dimensions advisory in its comprehensive CI lane. A2A already has stricter published defaults: cognitive complexity 15 in `pyproject.toml:375-376`, cyclomatic complexity 10 in `pyproject.toml:259-267`, and module size 1000 in `pyproject.toml:395-401`. The A2A health reporter uses Radon's API for cyclomatic and maintainability measurements, while Complexipy remains the sole cognitive-complexity authority; it must not be reimplemented in the reporter (`dev/health/report.py:23-33`).

Complexipy's configuration is process-global: a `[tool.complexipy] exclude` policy would apply to both `lint complexity` and A2A's separate `audit complexity` target. The latter is intentionally a test-focused investigation command, so production exclusions must remain target-specific command arguments in `dev/toolchain.py`, not global configuration. Complexipy 6.2 accepts root-relative exclusions and normalizes Windows paths; the production target must exclude both direct and nested test-tier plus cache paths while retaining the existing configured limit.

### Duplication and CI tiering

RAG and A2A both use production-only JSCPD at 20 lines and 70 tokens. In both cases it is advisory because clone reports are investigation leads rather than self-proving defects. Core has no clone detector to import. A2A should retain its existing detector and add named visibility in CI only as an advisory lane until the project adopts a clone adjudication rule.

RAG's minimal pull-request gate, GPU dispatch, and self-hosted resource controls are not applicable to A2A's static-quality contract. A2A should instead use Core's independent, non-cancelling static results and its own existing service/acceptance lanes, keeping hardware or provider-live prerequisites out of static CI.

### Required future verification

Before a target joins A2A `lint all`, prove a fresh zero-finding run at its existing threshold, repeat it on a settled checkout, run the canonical CI aggregate, and preserve an execution record. A direct test must also prove the root CI command and its `dev` equivalent invoke the same static target set so workflow drift cannot silently remove a promoted sentinel.
