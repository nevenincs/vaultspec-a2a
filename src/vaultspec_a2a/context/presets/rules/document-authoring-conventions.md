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

Body-prose conventions for vaultspec document authoring — the taxonomy, frontmatter,
linking, and template rules the engine does NOT validate server-side. These bind the
vault-document roles: the research_adr writers (researcher, synthesist,
adr-author, plan-author, doc-reviewer) and the solo doc-editor, which revises an
existing document and must satisfy the same conventions. A workspace file of the
same name overrides this bundled default entirely.

## Tag taxonomy

- Exactly TWO tags in the `tags:` list: one directory tag by location, one kebab-case
  `#<feature>` tag. No more, no less; a third tag reads as a second feature tag and
  fails validation.
- Directory tags: `#adr` `#audit` `#exec` `#index` `#plan` `#reference` `#research`.
- No structural tags (`#step`, `#phase1`, `#design`, CamelCase, spaces).

## Frontmatter schema

- Only `tags`, `date`, `related` (and the CLI-maintained `modified`) belong in
  frontmatter. Never add other keys; metadata that drifted into the body belongs back
  in frontmatter.
- `date` is `yyyy-mm-dd`.
- `related:` is a YAML list of QUOTED wiki-links: `- '[[stem]]'`. Never bare strings,
  never relative paths (`../`), never `@ref`.

## Wiki-links live ONLY in `related:` frontmatter

- A `[[wiki-link]]` appears ONLY in the `related:` field. NEVER in body prose.
- In the body, reference another document by bare stem or a backtick code span
  (`2026-07-15-feature-research`) — never `[[...]]`, never `[text](path)` markdown
  links. A `[[...]]` below the frontmatter is refused at materialization.

## Follow the template, never echo it

- Author FOLLOWING the section structure of `.vaultspec/templates/<type>.md`; fill
  every section with real content. NEVER reproduce the template's `<!-- -->` guidance
  comments and NEVER leave a `{placeholder}` unfilled — an echoed scaffold is not a
  document and is refused at submit.
- The first character of the emitted document is the opening `---` frontmatter fence;
  no preamble before it, no fenced code block around the document.

## Document boundary — each fact has one home

- The research grounds; the ADR decides; the plan sequences. Cite a research finding
  or a decision by stem rather than restating it; a restated fact forks context and
  goes stale silently.
- Decision language lives only in the ADR. A plan carries no rationale of its own — it
  cites the ADR that already argued it.

## Doc-type structure

- Research: answer-first lead paragraph (question, stakes, conclusion); each Findings
  subsection opens with its claim, evidence follows; a closing `## Sources` collecting
  every locator once.
- ADR: Problem Statement, Considerations, Constraints, Considered options (>= 2 with
  kept/rejected rationale), Implementation, Rationale, Consequences. The status rides
  the H1 token — `# <feature> adr: <title> | (**status:** accepted)` — never a
  separate `## Status` section.
- Plan: a `tier` (`L1`-`L4`) declared in frontmatter, a Goal stating what the plan
  delivers, and a Steps section of leaf rows. Every Step names one action, its scoped
  files, and a verifiable success criterion; a Step whose completion cannot be checked
  is not a Step. Cite the governing ADR by stem in `related:`, never re-argue it.

## Quality bar

- Every non-obvious claim carries a re-fetchable locator (`file:line`, URL,
  `package@version`, RFC, commit SHA); unverified general knowledge is flagged as
  opinion.
- Alternatives named with kept/rejected rationale; versions, dates, and numbers pinned
  (never "popular"/"widely used"); each fact stated once; no hedging boilerplate, no
  restated prompt, no empty closing summary.
