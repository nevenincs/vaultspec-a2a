---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S12'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Write adversarial mock-free tests for the deny policy covering direct, traversal, symlink, relative-path, and case-variant attempts against a live handler

## Scope

- `src/vaultspec_a2a/providers/tests/`

## Description

- Author `providers/tests/test_acp_vault_deny.py`: mock-free tests that drive the REAL `on_fs_write_text_file` / `on_fs_read_text_file` handlers against a real `tmp_path` workspace (a minimal real `_AcpModelConfig`; the write handler never touches ctx).
- Cover every write route into the vault: direct (`.vault/plan/x.md`), deeply nested, `..` traversal that resolves back into `.vault`, relative dot-prefixed (`./.vault/./notes.md`), case variants (`.VAULT`/`.Vault`/`.vAuLt`), and a symlink/junction that resolves to `.vault` — each asserted to return the `forbidden_actor` value denial and to write nothing.
- Prove the policy is surgical: a non-vault write actually lands, and a vault READ returns content (reads stay permitted).

## Outcome

Committed with S11 as `07f8c9c`. All 10 tests pass; `ruff` and `ty` clean. The symlink case uses a cross-platform `_link_dir` helper that prefers `os.symlink` and falls back to a Windows directory junction (`mklink /J`, no elevation needed) so it runs everywhere without a skip.

## Notes

UNC and 8.3-short-name vectors from the review list are not directly constructible inside a `tmp_path` (they need a real network share / a >8-char name with a generated short alias), so they are not asserted as literal path strings. They are covered by the same underlying logic that the tests DO exercise: `sandbox_path().resolve()` normalises UNC/short-name forms to a real path, and the `casefold()` component check is the same case-insensitivity vector an 8.3 alias would exploit. No skips, mocks, or monkeypatching were used, per mandate.
