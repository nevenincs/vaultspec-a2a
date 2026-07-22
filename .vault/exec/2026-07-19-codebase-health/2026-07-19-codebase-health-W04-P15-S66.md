---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S66'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Split ProviderFactory.create into explicit provider admission and construction paths

## Scope

- `src/vaultspec_a2a/providers/factory.py, tests/providers`

## Description

- Confirm the twenty-six-test factory suite covered create before touching it.
- Extract the admission path - the supported-provider guard and the model-name
  resolution - into a module function returning the resolved model name.
- Leave the per-provider construction in create as the construction path.
- Add tests exercising admission on its own.

## Outcome

The create method folded two concerns: admission - deciding whether the provider is
supported and what model name it resolves to - and construction, the per-provider
instantiation that follows. Admission is now a module function that create calls before any
construction begins, so a bad request fails at the boundary rather than partway through
building a model.

The twenty-six-test factory suite passes unchanged, so construction is unaffected. Four new
tests exercise admission directly: a default resolves through the model map, a model enum
resolves through it, a raw string passes through unvalidated, and an unsupported provider is
refused. That direct assertion is what the split unlocks - the resolution logic was
previously reachable only by constructing a whole model.

Gates: `ruff check` clean, `ty check` clean, and the providers suite reports three hundred
eighty-seven passed.

## Notes

The construction path was left in create rather than extracted into a second function. The
per-provider block is a sequence of guard-and-return branches that each build a different
model with different arguments, and moving it wholesale would have been a large verbatim
relocation for little gain over the admission split, which is the part that carried mixed
concerns. The step named two paths; admission was the one worth separating, and construction
reads clearly as what remains.

The supported-provider set moved from a local built on every call to a module-level frozen
constant, so it is allocated once rather than per invocation - a small, incidental
improvement the extraction made natural.
