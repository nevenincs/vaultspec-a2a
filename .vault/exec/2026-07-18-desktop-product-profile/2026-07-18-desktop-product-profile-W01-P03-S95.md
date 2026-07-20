---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S95'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Write deterministic capsule archives through one exact create-new file inside a caller-owned unpublished generation while sharing the bounded emitter and retaining fail-closed legacy publication behavior

## Scope

- `src/vaultspec_a2a/desktop/capsule_evidence.py`
- `src/vaultspec_a2a/desktop/tests/test_unpublished_generation.py`

## Description

- Add an explicitly unpublished-generation ZIP writer that consumes the caller's
  already-live generation authority.
- Claim the final archive name once through the exact create-new file primitive.
- Share the bounded deterministic emitter with legacy fail-closed publication.
- Bind enumerated source directories and files to stable identities through emission.
- Leave a partial final-name file in the inert generation after any late failure.
- Prove deterministic bytes, collision preservation, and failure retention with real
  production imports and filesystem authority primitives.

## Outcome

S95 adds `write_deterministic_capsule_zip_into_unpublished_generation`. The API
validates the caller's live generation authority, refuses source/output overlap,
claims one final portable filename without truncation or rename, emits through the
shared bounded ZIP implementation, hashes the held exact file, and revalidates source,
generation, and output authority throughout. A failure never cleans or selects the
generation; outer verification must reject the retained partial output.

Eight real unpublished-generation tests pass, including deterministic final-name
bytes, create-new collision preservation, and zero-byte failure retention. The
38-test focused archive/publication/build/verifier campaign and complete 262-test
desktop suite pass. Ruff, formatting, Ty, and diff hygiene pass for source hash
`B72C6B49947E2BBB449F114373BD229604DE2441FECCDBE77CE4FCD22A9DA35F`.

## Notes

Review renamed the public API to include the safety-critical `unpublished` qualifier,
made the caller's exclusive-mutation precondition explicit, reconciled the shared
emitter's type contract, and regenerated this record from the corrected canonical
plan scope. The unrelated gateway note was removed. Independent technical review
approved the exact recorded source state. S96 process/substitution coverage, S14
complete-generation verification, dashboard receipt selection, and target-native
release evidence remain open.
