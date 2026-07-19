---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S02'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Regenerate the locked Python graph and prove CPython 3.13 resolution for every accepted target

## Scope

- `uv.lock`

## Description

- Snapshot the pre-existing foreign lock bytes and compare their package inventory with the committed lock.
- Replay uv's pinned-version-preserving lock operation twice in isolation from committed `pyproject.toml` metadata.
- Regenerate and check the repository lock with CPython 3.13 without requesting upgrades.
- Export and partition-check the default, `server`, and `rag` closures.
- Evaluate exported platform markers for every accepted target and run frozen cross-target installation dry-runs.

## Outcome

The adopted lock contains 171 package records and requires Python `>=3.13`.
Its root metadata declares 22 default dependencies, published `server` and
`rag` extras, and the existing `dev` group. Package name, version, and source
inventory is identical to the committed predecessor. In addition to the root
dependency classification, uv normalized transitive environment-marker
metadata for CUDA and NVIDIA packages, Torch, and `phart`; no package identity,
version, or source changed.

The foreign candidate started as blob
`e9b84d14a7d1215fa62c95c9b020f7796fbeb80f` with 553,019 bytes and SHA-256
`2B24821FEBF1EDE3792E1A7B9F469729C641E018DA6A64C97B6EB5E42346D330`.
Two isolated non-upgrading regenerations from the committed project metadata
produced that exact digest, as did the canonical repository regeneration with
uv 0.11.29 and CPython 3.13.11. `uv lock --check` then passed.

Frozen default and `server` dry-runs passed for Apple Silicon macOS, Intel
macOS, Arm64 Linux, x86-64 Linux, and x86-64 Windows: 10 of 10 profile-target
combinations. Requirements exports contained 87 default, 98 server, and 146
RAG records. Partition assertions found no optional package leakage into the
default closure, and target marker evaluation selected exactly one appropriate
Torch requirement plus `vaultspec-rag` for all five target environments.

## Notes

RAG is a separately installed capability, not part of the accepted desktop base
closure, and its artifact support is narrower. The frozen RAG dry-run passes on
x86-64 Windows and on Arm64 or x86-64 Linux with a manylinux 2.34 baseline. It
does not install on generic manylinux 2.28 because
`tree-sitter-language-pack==1.6.1` provides Linux wheels only for manylinux
2.34. `torch==2.13.0` provides a CPython 3.13 macOS wheel only for macOS 14
Arm64, so uv's macOS 13 Arm64 target and Intel macOS target fail; Intel macOS
has no compatible locked Torch wheel. These are real optional-capability
eligibility limits and are not hidden or treated as passing evidence.

Cross-target uv dry-runs validate marker selection and installable distribution
availability from the lock; they do not execute native code on foreign hardware.
A supplemental dependency-only, wheel-only probe passed eight of ten default
and server combinations. Intel macOS requires building
`cryptography==49.0.0` from its locked source distribution because that release
has no x86-64 macOS wheel. Normal resolution remains green for both Intel macOS
profiles; the target capsule builder must either perform that native build or
materialize and certify the resulting wheel. Target-native capsule execution
remains assigned to the later capsule certification phase. The S02 plan row
remains open for independent review.
