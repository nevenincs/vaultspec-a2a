---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S11'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# Rewrite onboarding and add separated setup, command, operating-model, and vocabulary documentation through the documentation pipeline

## Scope

- `README.md`
- `docs`

## Description

- Replace the monolithic README with a concise onboarding path grounded in the
  executable Just and product command surfaces.
- Separate contributor setup, operator commands, architecture ownership, and
  shared terminology into focused Sphinx documents and navigation.
- Add security and contribution policies, structured issue forms, and a pull
  request template that carry the rolling review and validation contract.
- Run isolated technical and zero-context editorial review, apply every
  correction, and classify the findings in the rolling audit.
- Validate tracked diffs, Issue Form YAML, Markdown style, documentation tests,
  strict Sphinx output, and the external private-reporting route.

## Outcome

- Formal review status: PASS. No Critical or High issue remains.
- The public documentation now matches live Just recipes, product help,
  registry and Compose ownership, dependency profiles, and accepted
  architecture decisions.
- Documentation tests pass six cases, and the nitpicky warning-fatal Sphinx
  build succeeds.
- All three Issue Form YAML files parse, Markdownlint passes, and GitHub's API
  reports private vulnerability reporting enabled.

## Notes

- The unrelated concurrent `docs/api/modules.rst` change is explicitly excluded
  from this Step and commit.
- The existing audit queue retains live Unix doctor execution and terminal
  clone-to-CI acceptance for S12.
- No remote repository setting was changed and no commit was pushed.
