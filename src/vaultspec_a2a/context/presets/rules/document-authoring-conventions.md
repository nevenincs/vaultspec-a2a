---
order: 40
roles:
  - researcher
  - synthesist
  - adr-author
  - doc-reviewer
---

# Document-authoring conventions (research_adr)

Body-prose conventions for vaultspec document authoring — the taxonomy, frontmatter,
linking, and template rules the engine does NOT validate server-side. These bind the
research_adr document roles (researcher, synthesist, adr-author, doc-reviewer). A
workspace file of the same name overrides this bundled default entirely.

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

- The research grounds; the ADR decides. Cite a research finding by stem rather than
  restating its evidence; a restated fact forks context and goes stale silently.
- Decision language lives only in the ADR.

## Doc-type structure

- Research: answer-first lead paragraph (question, stakes, conclusion); each Findings
  subsection opens with its claim, evidence follows; a closing `## Sources` collecting
  every locator once.
- ADR: Problem Statement, Considerations, Constraints, Considered options (>= 2 with
  kept/rejected rationale), Implementation, Rationale, Consequences. The status rides
  the H1 token — `# <feature> adr: <title> | (**status:** accepted)` — never a
  separate `## Status` section.

## Quality bar

- Every non-obvious claim carries a re-fetchable locator (`file:line`, URL,
  `package@version`, RFC, commit SHA); unverified general knowledge is flagged as
  opinion.
- Alternatives named with kept/rejected rationale; versions, dates, and numbers pinned
  (never "popular"/"widely used"); each fact stated once; no hedging boilerplate, no
  restated prompt, no empty closing summary.
