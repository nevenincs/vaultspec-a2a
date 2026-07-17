---
tags:
  - '#audit'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
related:
  - '[[2026-07-17-kimi-provider-adr]]'
  - '[[2026-07-17-kimi-provider-research]]'
  - '[[2026-07-17-kimi-provider-plan]]'
  - '[[2026-07-17-tool-cores-adr]]'
  - '[[2026-07-15-multi-provider-execution-adr]]'
  - '[[2026-07-15-agent-harness-provisioning-adr]]'
---
# `kimi-provider` audit: `P06.S19 vault dedup sweep — decision-vs-decision, decision-vs-code, and grounding-staleness reconciliation`

## Scope

Semantic sweep of the vault for duplicate or overlapping `kimi-provider` records
(the VAULT half of P06.S19; the CODE dedup half was gated at plan step `P01.S01`),
run per the reconciliation playbook. Covers: (1) decision-vs-decision overlap with
`tool-cores` (the lane's inherited read-only contract), `multi-provider-execution`
(provider-lane precedent for Codex/Claude/Z.ai), and `agent-harness-provisioning`
(the system-wide harness contract); (2) decision-vs-code for the ADR's chosen shape
(b1, native ACP reuse) against the landed `Provider.KIMI` enum, factory dispatch, and
backend-conditioning code; (3) a known grounding-staleness item — the ADR/research
naming the Windows shell-override environment variable `KIMI_SHELL_PATH`, later
corrected by installed-source verification to `KIMI_CLI_GIT_BASH_PATH` — and whether
that correction has propagated back into the governing documents. Method:
`vaultspec-rag search --type vault --doc-type adr,research`, `vault list --feature
kimi-provider --json`, the feature index, whole-file reads of the `kimi-provider`
ADR/research/plan and the `P01.S05` exec record, and targeted greps of
`src/vaultspec_a2a/graph/enums.py` and `src/vaultspec_a2a/providers/factory.py`.

## Findings

### feature-index-drift | low | `kimi-provider` feature index was stale (10 links vs 15 documents)

`vaultspec-core vault check all --fix` reported the `kimi-provider` feature index
missing five later exec records (`P02-S07` through `P03-S13`). Mechanical, status-drift
class. Actioned directly.

### no-decision-duplication | none | clean against tool-cores, multi-provider-execution, and agent-harness-provisioning

The `kimi-provider-adr` correctly treats `tool-cores-adr` and `agent-harness-provisioning-adr`
as governing constraints it must conform to (read-only boundary, one registry, per-run
isolation, permission-RPC exact-name enforcement) rather than re-deciding them: its own
Constraints section cites both by wiki-link for the read-only invariant instead of
restating their Rationale. `multi-provider-execution-adr` (2026-07-15, scope "Codex,
Claude, and Z.ai") is historical and not re-opened: `kimi-provider-adr`'s Problem
Statement correctly frames Kimi as an ADDITIVE fourth lane on top of that record ("The
research-to-ADR authoring graph runs Claude, Codex, and Z.ai lanes... The owner wants
Kimi... added as a fourth lane"), and the multi-provider-execution ADR makes no claim
of exhaustiveness that this contradicts. `Provider.KIMI = "kimi"` in
`src/vaultspec_a2a/graph/enums.py:135` is additive, no existing member renamed,
matching the ADR's "additive, never-renaming" constraint and the multi-provider-execution
v1-additive precedent. No sibling `accepted` ADR was found deciding the same
provider-lane-integration-shape scope for Kimi/Moonshot; rag search for "provider lane
ACP backend discriminator addition Kimi Moonshot fourth lane" against
`--type vault --doc-type adr,research` returned no competing record (only an unrelated
`layer2d` ADR as a low-relevance false-positive top hit, confirmed irrelevant by
content). No duplication or contradiction found.

### decision-vs-code-conforms | none | Provider.KIMI plumbing and the Git-Bash grounding correction are both landed as decided

Grepped `src/vaultspec_a2a/graph/enums.py` and `src/vaultspec_a2a/providers/factory.py`:
`Provider.KIMI = "kimi"` with `MODEL_MAP`/`PROVIDER_DEFAULT_MODELS` entries exist per
`P01.S02`; `_KIMI_CLI_PIN`, `_KIMI_INSTALL_HINT`, `_KIMI_GIT_BASH_ENV =
"KIMI_CLI_GIT_BASH_PATH"`, and `_kimi_git_bash_resolvable()` exist per `P01.S05`, with an
inline code comment already noting the correction ("grounding the installed source
corrected the env name from the ADR's inferred 'KIMI_SHELL_PATH' to the actual
'KIMI_CLI_GIT_BASH_PATH'", `factory.py:322-323`). Code matches the ADR's decided shape
(b1); no drift.

### grounding-staleness-unpropagated | medium | ADR and research still name the superseded `KIMI_SHELL_PATH`; the correction lives only in the exec record and code comment

Both governing documents predate the correction and were never amended after it. The
ADR's Considerations (line 29, "`KIMI_SHELL_PATH` overrides") and Implementation
(line 62, '"honoring KIMI_SHELL_PATH" from the Step text') sections, and the research
document's "Kimi Code CLI" (line 52) and "Live probe results" (line 158-159) sections,
all state the env var is `KIMI_SHELL_PATH`. The `P01.S05` exec record documents a
"GROUNDING CORRECTION (installed-source re-grounding superseded the ADR)": the
installed `kimi-cli` 1.49.0 source (`utils/environment.py:100`) and its CHANGELOG read
`KIMI_CLI_GIT_BASH_PATH`, not `KIMI_SHELL_PATH` — the ADR/research name was an inferred
guess from documentation, now falsified by source-of-truth verification, and the exec
record explicitly says this is recorded "so a future ADR reader is not misled." That
correction has not yet been back-propagated into the ADR or research bodies themselves,
so a reader of either document today still encounters the superseded name with no
pointer to the correction. This is a restated/superseded-grounding class finding
(content-preserving, safe to fix once approved) — not a contradiction requiring
resolution, since the code and its comment already carry the truth; it is a documentation
currency gap. Per the assignment, drafted below rather than applied to the ADR directly.

## Recommendations

- **Actioned directly (mechanical, no approval needed):** regenerated the
  `kimi-provider` feature index via `vaultspec-core vault feature index -f
  kimi-provider`.
- **Recommend a dated correction annotation on `2026-07-17-kimi-provider-adr`**,
  appended after the Consequences section (mirroring the dated-Amendment convention
  used elsewhere in the vault, e.g. `agent-harness-provisioning-adr`'s 2026-07-17
  amendment), reading substantially:

  > ## Correction (2026-07-17, `P01.S05` grounding correction)
  >
  > The Considerations and Implementation sections above name the Windows shell-override
  > environment variable as `KIMI_SHELL_PATH`. Installed-source re-grounding during
  > execution (`P01.S05`) found this was an inferred name, falsified by the installed
  > `kimi-cli` 1.49.0 source (`utils/environment.py:100`) and its CHANGELOG, which read
  > `os.environ.get("KIMI_CLI_GIT_BASH_PATH")`. The correct override name is
  > `KIMI_CLI_GIT_BASH_PATH`; the landed code (`factory.py:_KIMI_GIT_BASH_ENV`) uses the
  > corrected name and the resolution order this ADR describes (env override, then
  > `git`/`bash` on PATH, then standard install path) is otherwise accurate and unchanged.
  > `KIMI_SHELL_PATH` does not exist in the `kimi-cli` source and should not be treated
  > as a valid override in any future reference to this record.

  A parallel one-line correction is recommended for `2026-07-17-kimi-provider-research`
  at its two `KIMI_SHELL_PATH` mentions (a short "corrected to `KIMI_CLI_GIT_BASH_PATH`,
  see `kimi-provider-adr` correction" pointer), since research is a grounding document
  and the same stale name appears there too, in the same content-preserving,
  safe-to-fix class. Both are drafted here as recommendations rather than applied,
  per the assignment; no decision content changes — the chosen shape (b1) and every
  other constraint are unaffected. No follow-on ADR is needed; this is a documentation
  correction, not an architectural change.
- No contradiction, duplication, or fragmented decision was found across the
  `kimi-provider` cluster or against `tool-cores`, `multi-provider-execution`, or
  `agent-harness-provisioning`.
