---
date: 2026-03-19
tags: ["#plan", "#apple-tree"]
related: []
---

# Plan: Apple Tree Module — Phase 1

## Goal

Create a self-contained `apple_tree` Python module under `temp/` that defines
`Apple` and `AppleTree` classes, a runnable `main.py` entrypoint, and a unit
test suite exercising the `pick()` method.

## Scope

Single phase. The module is entirely new with no cross-cutting concerns,
no ADR constraints, and no external service dependencies.

## Target File Tree

```
temp/
  apple_tree/
    __init__.py
    apple.py
    apple_tree.py
    tests/
      __init__.py
      test_apple_tree.py
  main.py
```

## Phase 1 — Implementation

### Steps

- Name: Define Apple dataclass
- Step summary: Step Record (`.vault/exec/2026-03-19-apple-tree/2026-03-19-apple-tree-phase-1-step-1.md`)
- Executing sub-agent: vaultspec-coder
- References: none

  Create `temp/apple_tree/apple.py`.
  `Apple` has two attributes: `color: str` and `variety: str`.
  Use a plain class with `__init__` and `__repr__`.

---

- Name: Define AppleTree class
- Step summary: Step Record (`.vault/exec/2026-03-19-apple-tree/2026-03-19-apple-tree-phase-1-step-2.md`)
- Executing sub-agent: vaultspec-coder
- References: none

  Create `temp/apple_tree/apple_tree.py`.
  `AppleTree` holds a `list[Apple]` passed at construction.
  `pick() -> Apple` removes and returns the last apple from the list.
  Raise `IndexError` with a clear message when the list is empty.

---

- Name: Expose public API via __init__.py
- Step summary: Step Record (`.vault/exec/2026-03-19-apple-tree/2026-03-19-apple-tree-phase-1-step-3.md`)
- Executing sub-agent: vaultspec-coder
- References: none

  Create `temp/apple_tree/__init__.py`.
  Re-export `Apple` and `AppleTree` so consumers can write
  `from apple_tree import Apple, AppleTree`.
  Declare `__all__ = ["Apple", "AppleTree"]`.

---

- Name: Write main.py entrypoint
- Step summary: Step Record (`.vault/exec/2026-03-19-apple-tree/2026-03-19-apple-tree-phase-1-step-4.md`)
- Executing sub-agent: vaultspec-coder
- References: none

  Create `temp/main.py`.
  Instantiate `AppleTree` with 5 `Apple` objects (varying color + variety).
  Call `pick()` three times in a loop and print each result.
  Guard under `if __name__ == "__main__"`.

---

- Name: Write unit tests for pick()
- Step summary: Step Record (`.vault/exec/2026-03-19-apple-tree/2026-03-19-apple-tree-phase-1-step-5.md`)
- Executing sub-agent: vaultspec-coder
- References: none

  Create `temp/apple_tree/tests/test_apple_tree.py` (pytest, no mocks).
  Test cases:
  1. `pick()` returns an `Apple` instance.
  2. `pick()` reduces the tree's apple count by 1 each call.
  3. `pick()` on an empty tree raises `IndexError`.
  4. Successive `pick()` calls return apples in LIFO order.

## Success Criteria

- `python temp/main.py` runs without error and prints 3 apple descriptions.
- `pytest temp/apple_tree/tests/` passes all 4 test cases with no mocks.
- `Apple` and `AppleTree` are importable from `apple_tree` package root.
