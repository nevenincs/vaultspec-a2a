---
tags:
  - '#research'
  - '#tool-cores'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:5489e8c91264c41686a405cacb94c7879cdf8bedd71c2e94a6a531d516e4518e'
related:
  - "[[2026-07-17-tool-cores-adr]]"
  - "[[2026-07-17-tool-cores-research]]"
---
# `tool-cores` research: `provider-native web grounding`

## Question

The graph's document agents ground on internal sources only. The registry that
serves them is closed by design and currently holds one entry. A downstream
decision record asks for web search and fetch in the researcher harness. The
open questions are whether outbound grounding is reachable without adding a
vendor dependency or a credential, what each provider lane already ships, and
what the resulting exposure actually is.

## Findings

### Every provider lane already ships web tools; none needs a key from us

The three lanes carry first-party web capability today, licensed under the same
provider subscription that already authenticates the run. No third-party search
vendor, API key, or per-call billing is implicated in reaching parity with what
the CLIs natively do.

The names differ per lane and are exact:

- The Claude CLI exposes `WebSearch` and `WebFetch` as built-in tools, siblings
  of the `Read`, `Grep`, and `Glob` built-ins already permitted. Z.ai inherits
  this unchanged, being the same transport with an environment-only difference.
- The Gemini CLI exposes `google_web_search` and `web_fetch`.
- The Codex CLI does not expose them as allowlistable tool names at all. Web
  search is a configuration feature toggled in its config file, which is the
  same seam the existing per-run config home already writes.

The split is not incidental: it reproduces exactly the delivery-shape asymmetry
the governing decision already records between its Claude and Codex legs, where
the capability is shared and only the serialization differs.

### Correction, from the installed binary rather than documentation

The finding below was first taken from published configuration documentation,
which describes the mode as a feature-table entry. Verification against the
installed command-line tool at version 0.146.0 shows that is wrong, and the
binary is the authority.

The mode is a TOP-LEVEL key in the configuration file, not an entry under the
feature table. The two feature-table forms both report as deprecated, and the
binary carries its own migration string instructing that the key be set at the
top level or under a profile. The parser refuses an unknown value by naming the
four it accepts, which is stronger evidence than any documentation page because
it is the parser speaking.

One structural consequence follows and it is not cosmetic. Because a top-level
key placed after a table header belongs to that table, the mode must be emitted
BEFORE any declared-server table in the generated file. Emitting it afterwards
produces a file that parses cleanly and means something entirely different -
silent misconfiguration rather than a loud failure - so the ordering needs a test
of its own rather than a test that merely asserts the key is present.

### The Codex lane has a third mode that changes the exposure question

Codex's web search is not a binary. Its documented modes are a cached mode
serving a provider-maintained index with no external access at all, an indexed
mode permitting external access only when gated by that index, a live mode for
unrestricted retrieval, and disabled. The cached mode became the client default
in the January 2026 build.

This matters because it means one lane can offer genuine search with no outbound
request from the agent host, which is a materially different posture from the
other two and is available without any work beyond choosing the mode.

The feature was previously off by default, and the reason on record was
experimental status together with prompt-injection concern - the same hazard
named independently below.

### The first-party tools carry their own constraints, and one is a real control

The Claude fetch tool is documented as only able to retrieve URLs the user
supplied or that came from a previous search or fetch result. That is a
meaningful bound: it is not a general outbound HTTP client, and it cannot be
pointed at an arbitrary internal address on a whim.

The same tool surface documents optional domain allowlisting and blocklisting,
a cap on uses per request, and a cap on returned content tokens. Domain
allowlisting is the strongest available control and is a first-party feature
rather than something this project would have to build.

### The exposure is indirect prompt injection, and the authoritative guidance is that it cannot be prompted away

The framework's own security guidance states plainly that retrieved content
shares the context window with the system prompt, that models may follow
instructions embedded in retrieved text, and that no prompt or delimiter
strategy fully prevents this. The recommended mitigations are treating retrieved
content as data, marking its provenance so a reader can distinguish metadata
from body, and validating that outputs cite the sources they claim.

Separately and more sharply, the provider's own web-fetch documentation warns
that enabling fetch where the model processes untrusted input alongside
sensitive data poses a data-exfiltration risk, and recommends confining it to
trusted environments or non-sensitive data.

That warning is the one that bears hardest here, because it names the axis the
existing registry does not model. The registry's read-only marker asserts that
an entry does not write locally. A fetch tool satisfies that marker completely
while still being capable of carrying workspace content outward in a URL. Local
write and network egress are independent properties, and only the first is
currently expressed.

### The composition seam this would use already exists and is narrow

The native built-ins are unioned into the session allowlist by exact name, for
autonomous runs and document-authoring roles only, never by wildcard, and never
for human-in-the-loop runs, which keep their prompts. Human-in-the-loop runs
therefore already gate any new tool behind the existing permission interrupt
without further work.

The Codex config-home seam is the established counterpart, already threaded per
run and already carrying the declared servers in that provider's native shape.

## Implications

Reaching the requested capability requires no new registry entry, no vendor, no
credential, and no new machinery. It is a permission and configuration change
over two seams that already exist, which is a substantially smaller surface than
adding a server would have been.

The decision that remains is not technical feasibility but exposure. Three
things are genuinely open and belong in the governing record rather than here:
whether the read-only marker should be split so that network reach is expressed
separately from local write; whether the capability is scoped to the researcher
role alone or to all document-authoring roles; and whether the Codex lane's
cached mode should be the default posture given it delivers search with no
outbound request at all.

## Sources

Provider tool surfaces and their documented constraints were taken from the
Claude Code tool documentation, the Gemini CLI tool reference, and the Codex
configuration reference, all read live rather than from recall. The injection
and exfiltration guidance was taken from the framework's own security pages and
from the provider's web-fetch tool documentation.
