---
name: "Distilled Documents Index"
date: 2026-25-02
type: index
summary: "Master index for per-domain distilled documents. Each distilled doc consolidates raw research, removes refuted hypotheses, and explicitly flags contradictions and knowledge gaps."
---

# Distilled Documents

Curated, per-domain summaries that consolidate the raw research in `docs/`.
Each distilled document:

- **Removes** refuted and discarded hypotheses
- **Flags** contradictions that need ADR resolution
- **Identifies** knowledge gaps that block decisions
- **Traces** back to source documents for provenance

Raw research is preserved as-is in the original `docs/` subdirectories.

---

## Documents

| Domain | File | Sources | Maturity | Status |
|--------|------|---------|----------|--------|
| Agents | [2026-25-02-agents-distilled.md](2026-25-02-agents-distilled.md) | 4 files from `docs/agents/` | 45 | Complete |
| Architecture | [2026-25-02-architecture-distilled.md](2026-25-02-architecture-distilled.md) | 6 files from `docs/architecture/` | 50 | Complete |
| Protocols | [2026-25-02-protocols-distilled.md](2026-25-02-protocols-distilled.md) | 2 files from `docs/protocols/` | 45 | Complete |
| Control Surface | [2026-25-02-control-surface-distilled.md](2026-25-02-control-surface-distilled.md) | 2 files from `docs/control-surface/` | 40 | Complete |
| Process | [2026-25-02-process-distilled.md](2026-25-02-process-distilled.md) | 2 files from `docs/process/` | 40 | Complete |

## Cross-Domain Concerns

As distillation progresses, cross-cutting contradictions and gaps that span
multiple domains will be collected here.

| ID | Concern | Domains | Status |
|----|---------|---------|--------|
| X1 | ACP richness gap: 11 typed updates vs A2A's generic Message.parts[]. Agents speak A2A but lose semantic distinction between thoughts, tool calls, and plan updates. | Protocols, Architecture | Needs ADR |
| X2 | Windows CLI compatibility untested for Claude and Gemini. Codex flags it as critical. Project constraint is Windows 11 PWSH, no WSL. | Agents, Process | Needs investigation |
| X3 | Token lifecycle (expiry, refresh, mid-session failure) undefined across all providers. | Agents, Architecture | Needs investigation |
| X4 | OTel integration timing: monitoring research recommends from day one; v1 scope doesn't include it. | Process, Architecture | Needs ADR |
| X5 | LangGraph and LiteLLM listed as options but never evaluated or formally discarded. | Architecture | Needs ADR |
