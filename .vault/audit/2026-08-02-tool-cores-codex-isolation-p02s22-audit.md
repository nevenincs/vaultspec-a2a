---
tags:
  - '#audit'
  - '#tool-cores'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:6c075c33ead58c7461e61fde41cc812a2b129e1b4abb76c701f8c1630def3181'
related:
  - "[[2026-08-01-tool-cores-plan]]"
---
# `tool-cores` audit: `Codex isolation P02.S22 review`

## Scope

Review of worker-owned Codex configuration-home isolation, early app-server failure diagnostics, and the one-turn low-tier certification proof.

## Findings

### ambient-mcp-isolation | high | resolved

An unarmed Codex model previously inherited the operator configuration because no worker-owned home was created for an empty declared server set. Every turn now receives an isolated home containing only copied authentication and the explicit run posture.

### startup-diagnostics | medium | resolved

Unexpected app-server EOF previously discarded the retained stderr and process status. The provider now reports the exit code and a bounded, redacted diagnostic tail.

### diagnostic-test-auth-boundary | medium | resolved

The first diagnostic regression used the default operator home. It now supplies an empty test-owned home, so a non-live test cannot copy the operator authentication file.

### low-tier-certification | medium | resolved

The real provider test now asserts the factory-created Codex model carries the exact low concrete name before it sends a prompt, then verifies one meaningful real response.

## Recommendations

- Keep the one-turn low-tier Codex service proof as the lane-admission certification.
- Treat future startup failures as observable provider incidents; do not reintroduce ambient configuration as a workaround.
