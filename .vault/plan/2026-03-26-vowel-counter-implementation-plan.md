---
tags:
- '#plan'
- '#vowel-counter'
date: 2026-03-26
modified: '2026-07-15'
related:
- '[[2026-03-31-docs-vault-authority-retention-adr]]'
- '[[2026-03-31-docs-vault-migration-research]]'
---

# vowel-counter-implementation-plan

This plan outlines the steps to implement a Python function for counting vowels in a string and to create corresponding unit tests.

## Goal

Implement a `count_vowels` function in `src/vaultspec_a2a/utils` that takes a string as input and returns the number of vowels (a, e, i, o, u, case-insensitive) in it. Additionally, create a comprehensive set of unit tests in `src/vaultspec_a2a/tests` to ensure the function's correctness.

## Phases

### Phase 1: Implementation and Testing

This phase focuses on developing the `count_vowels` function and its associated unit tests.

#### Steps

- Name: Implement `count_vowels` function
- Step summary: Implement the `count_vowels` function in a new Python file within `src/vaultspec_a2a/utils`.
  (`.vault/exec/2026-03-26-vowel-counter/2026-03-26-vowel-counter-phase-1-implement-function.md`)
- Executing sub-agent: vaultspec-coder
- References: []

- Name: Create unit tests for `count_vowels`
- Step summary: Create a new Python test file in `src/vaultspec_a2a/tests` and write unit tests for the `count_vowels` function, covering various test cases (e.g., empty string, string with no vowels, string with all vowels, mixed case, special characters).
  (`.vault/exec/2026-03-26-vowel-counter/2026-03-26-vowel-counter-phase-1-create-tests.md`)
- Executing sub-agent: vaultspec-coder
- References: []

- Name: Run tests
- Step summary: Execute the newly created unit tests to verify the correctness of the `count_vowels` function.
  (`.vault/exec/2026-03-26-vowel-counter/2026-03-26-vowel-counter-phase-1-run-tests.md`)
- Executing sub-agent: vaultspec-coder
- References: []

PLAN READY
