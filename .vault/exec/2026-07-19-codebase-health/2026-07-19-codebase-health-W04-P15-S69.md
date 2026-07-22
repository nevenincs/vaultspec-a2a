---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S69'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Split normalize_tool_input_schema into explicit schema-shape translators

## Scope

- `src/vaultspec_a2a/streaming/transformer.py, tests/streaming`

## Description

- Confirm the dedicated schema-normalize suite covered the function before
  touching it.
- Extract the two DSL shape branches - oneOf and flat - into named translators
  returning their JSON-Schema fragments.
- Keep the passthrough guards and the final assembly in the public function.
- Add tests exercising each translator on its own.

## Outcome

The normaliser branched over three shapes in one body: a non-dict or
already-valid-JSON-Schema passthrough, a oneOf DSL schema, and a flat DSL schema. The two
DSL branches are now named translators that each return their properties, required set, and
open-or-closed decision, with the public function dispatching on shape and assembling the
bounds, engine-keyword guidance, and final schema.

The dedicated fourteen-test schema-normalize suite passes unchanged, so the composed output
is identical. Six new tests exercise the translators directly: the flat translator's
required-and-optional enumeration, its payload-opens-the-schema rule, and its injected-id
drop; the oneOf translator's per-branch required intersection, its payload-opens rule, and
its discriminator enum. That direct assertion is the capability the split unlocks - the
combined function only ever exposed the merged result.

Gates: `ruff check` clean, `ty check` clean, and the MCP suite reports eighty-six passed.

## Notes

Two of the new tests first used ``command`` as the discriminator field. The real
discriminator keys are ``target`` and ``operation``; ``command`` matched nothing, so the
tests failed against correct code. Reading the discriminator constant fixed them. This is
the same lesson that has recurred across this session: the symbol names come from the code,
not from what a field is intuitively called.

The extraction required one type widening the mechanical move could not carry. After the
non-dict guard, the checker narrows the raw schema to a dict of unknown key and value types
rather than a string-keyed one, so the flat translator's parameter is typed as that looser
dict to accept the narrowed value without a cast or a suppression.

The step's scope names the transformer; the function lives in the MCP schema-normalize
module. The split was made where the function is defined, and no transformer code was
involved.
