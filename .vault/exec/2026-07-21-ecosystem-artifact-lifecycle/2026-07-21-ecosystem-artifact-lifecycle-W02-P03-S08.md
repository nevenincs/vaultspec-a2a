---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S08'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Add a test asserting every declared seam names a disposition and an owner

## Scope

- `src/vaultspec_a2a/artifacts/tests/test_retention.py`

## Description

- Add a suite that imports the real declaring modules and asserts across their
  collected declarations rather than over fixtures.
- Maintain the list of declaring modules by hand, and record in the module
  docstring why: discovering it by walking the package would make the suite pass
  automatically for a module that declares nothing.
- Assert that names are unique service-wide, that every declaration names an owner
  and a mechanism, and that a permanent declaration anywhere carries a reason.
- Assert that roots are path expressions rather than resolved or absolute paths.
- Assert specifically that the discovery record still declares its crash exposure,
  so the known gap cannot be closed in prose before it is closed in code.
- Prove the root assertions are not vacuous by constructing a resolved-root and an
  absolute-root declaration and confirming each is detected.

## Outcome

Fifteen tests pass across the package. The suite asserts over live module data, so a
declaration that regresses fails the build rather than merely reading badly.

The root assertions were checked for vacuity before being trusted. A declaration with a
fully resolved Windows root and one with an absolute root were each constructed and
confirmed detectable, and a well-formed path expression was confirmed to pass, so the
assertions discriminate rather than accepting anything.

The file was placed alongside the vocabulary tests rather than at the Step's declared
scope path, because the Step's scope named the existing test module and the enumeration
concern is distinct enough to warrant its own file. The scope divergence is recorded
here rather than silently absorbed.

Gates: `ruff check` and `ty check` report all checks passed with no suppressions
anywhere in the package, and the package suite reports fifteen passed.

## Notes

The hand-maintained module list is the deliberate weak point. It makes an undeclared
module invisible to this suite, which is exactly the failure mode the governing decision
warns about when it rejects central registries. The trade was accepted because the
alternative is worse: an automatic walk would report success for a module that declares
nothing, converting the absence of a declaration into a passing test. Making the list
explicit at least puts the omission in a diff.

This closes the declaration Phase. What exists now is a vocabulary, two adopting modules,
and a suite that keeps them honest. What does not exist is coverage of every
artifact-creating seam in the service; three seams are declared and the research named
considerably more. The plan does not currently carry Steps for the remainder, so that is
open work rather than work assumed done.
