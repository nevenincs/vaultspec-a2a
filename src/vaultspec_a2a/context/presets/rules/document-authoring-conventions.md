---
order: 40
roles:
  - researcher
  - synthesist
  - adr-author
  - plan-author
  - doc-reviewer
  - doc-editor
---

# Document-authoring conventions

What this runtime adds to the framework's own rules — not a restatement of them.

The vaultspec-core corpus installed at `.vaultspec/rules/` is the canonical home for
the tag taxonomy, the frontmatter schema, the placeholder conventions, and the
document dependency graph, and it is compiled into this same turn alongside this
file. The doc-type section structures are owned by `.vaultspec/templates/<type>.md`.
Both reach you already; a copy here would be a second source that goes stale
silently and contradicts the first without anyone noticing.

So what follows is only what core does not say: the emission mechanics this
runtime refuses on, and the editorial bar the phase gates hold you to. When this
file and the core corpus appear to disagree, the core corpus wins — report the
disagreement rather than picking.

These bind the vault-document roles: the research_adr writers (researcher,
synthesist, adr-author, plan-author, doc-reviewer) and the solo doc-editor, which
revises an existing document and must satisfy the same conventions. A workspace
file of the same name overrides this bundled default entirely.

## Emission mechanics this runtime refuses on

- A `[[wiki-link]]` appears ONLY in the `related:` frontmatter field, never in body
  prose. In the body, reference another document by bare stem or a backtick code
  span (`2026-07-15-feature-research`) — never `[[...]]`, never a
  `[text](path)` markdown link. A `[[...]]` below the frontmatter is refused at
  materialization.
- The first character of the emitted document is the opening `---` frontmatter
  fence: no preamble before it, and no fenced code block wrapped around the
  document.
- Fill every section of the template with real content, and never reproduce its
  `<!-- -->` guidance comments. An echoed scaffold is refused at submit.

## Document boundary — each fact has one home

- The research grounds; the ADR decides; the plan sequences. Cite a research
  finding or a decision by stem rather than restating it; a restated fact forks
  context and goes stale silently.
- Decision language lives only in the ADR. A plan carries no rationale of its own —
  it cites the ADR that already argued it.

## Quality bar

- Every non-obvious claim carries a re-fetchable locator (`file:line`, URL,
  `package@version`, RFC, commit SHA); unverified general knowledge is flagged as
  opinion.
- Alternatives named with kept/rejected rationale; versions, dates, and numbers
  pinned (never "popular"/"widely used"); each fact stated once; no hedging
  boilerplate, no restated prompt, no empty closing summary.
