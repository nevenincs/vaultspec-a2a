---
description: Internalize all binding ADRs and distilled documents to pre-populate context before starting work
---

# Internalize ADRs

This workflow reads all Architecture Decision Records and their supporting
distilled research documents. Run this at the start of any new conversation
that involves implementation, design, or architectural work on the project.

ADRs are **binding** — they must be strictly followed. Distilled documents
provide the supporting rationale and research context behind each ADR.

## Steps

// turbo-all

1. Read GEMINI.md for project-level rules and constraints:

```
cat Y:\code\vaultspec-a2a-worktrees\main\.gemini\GEMINI.md
```

1. Read all 9 ADRs (these are binding decisions):

```
Get-ChildItem -Path "Y:\code\vaultspec-a2a-worktrees\main\docs\adrs" -Filter "*.md" | ForEach-Object { Write-Host "=== $($_.Name) ==="; Get-Content $_.FullName -Raw; Write-Host "" }
```

1. Read the distilled document index and all distilled summaries:

```
Get-ChildItem -Path "Y:\code\vaultspec-a2a-worktrees\main\docs\distilled" -Filter "*.md" | ForEach-Object { Write-Host "=== $($_.Name) ==="; Get-Content $_.FullName -Raw; Write-Host "" }
```

1. Read the docs README for the full documentation map and maturity scores:

```
Get-Content "Y:\code\vaultspec-a2a-worktrees\main\docs\README.md" -Raw
```

1. After reading all documents, confirm readiness by summarising:

   - The 9 ADR titles and their core decisions
   - The module hierarchy (ADR-009)
   - The tech stack (ADR-007)
   - The protocol strategy (ADR-003, ADR-006)
   - Any open contradictions or knowledge gaps from the distilled documents
   - State that you are ready to proceed with implementation work
