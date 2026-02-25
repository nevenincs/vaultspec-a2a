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
| Architecture | *pending* | 6 files from `docs/architecture/` | — | Not started |
| Protocols | *pending* | 2 files from `docs/protocols/` | — | Not started |
| Control Surface | *pending* | 2 files from `docs/control-surface/` | — | Not started |
| Process | *pending* | 2 files from `docs/process/` | — | Not started |

## Cross-Domain Concerns

As distillation progresses, cross-cutting contradictions and gaps that span
multiple domains will be collected here.

| ID | Concern | Domains | Status |
|----|---------|---------|--------|
| — | *None yet — will emerge as more domains are distilled* | — | — |
