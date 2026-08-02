---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ea3227f262283d5be48900329676e38d693958ac60afacb34d5703bfd782950f'
step_id: 'S41'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace provider-error-taxonomy with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S41 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Remove the dead severity and recovery-action vocabulary and ## Scope

- `src/vaultspec_a2a/thread/errors.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Remove the dead severity and recovery-action vocabulary

## Scope

- `src/vaultspec_a2a/thread/errors.py`

## Description

- Verify independently that the severity and recovery-action vocabulary has no
  production reader, by AST scan rather than by text search.
- Delete the `ErrorSeverity` and `RecoveryAction` enumerations and the now-unused
  `StrEnum` import from `src/vaultspec_a2a/thread/errors.py`.
- Delete the two class-level declarations from all eleven `VaultspecError`
  subclasses that carried them.
- Delete `VaultspecError.__init__`, whose only work was applying the per-instance
  overrides of those two attributes, leaving a stateless common root.
- Withdraw both names from the module's `__all__`.
- Rewrite the module docstring, which described the module as a severity and
  recovery-hint classifier, and drop the one subclass docstring clause that
  promised an abort recovery action.
- Delete the tests whose only subject was the removed vocabulary.

## Outcome

The exception hierarchy now names only WHERE a failure happened. WHY a provider
refused work is answered by the provider condition vocabulary, resolved at the
lane from the discriminator the provider itself put on the wire, so the tree no
longer carries two competing answers to the same question with one of them
unread.

The zero-reader claim was confirmed independently before anything was deleted,
by parsing every module under `src`, `dev`, and `scripts` and reporting every
name load, attribute access, keyword argument, parameter, annotation, assignment
target, import, and string constant touching either enum or either attribute
name. That method was chosen over text search because a text search cannot
distinguish a read from a write, and because string constants are where a
dynamic `getattr` reader would hide. It found 140 references, every one of them
inside the errors module itself, its own package facade re-export, and its own
test module: the constructor's writes, the per-class declarations, the two
`__all__` entries, and the tests. Nothing outside `thread` referenced either
name in any form. A separate search for a dynamic `getattr` reader and for
references in non-Python files each returned nothing.

The removal is also confirmed after the fact rather than only before it: a
whole-tree type check passes, and whole-tree test collection imports every
module in the package without error, which is what would break first if any
importer still expected either name.

`ProviderSessionError` is untouched as a class. Only its two dead attribute
declarations were removed; it remains exported and remains referenced by the
graph compiler's no-retry set, so nothing was stranded.

## Notes

The vocabulary's removal is split across two Steps by file, and only the second
restores an importable tree: this Step deletes the definitions while the thread
package facade still re-exports them, so this commit alone does not import. The
next Step withdraws the re-exports and closes it. Both halves were edited and
verified together before either was committed, so the gates reported here
describe the state the pair lands, not the state of this commit in isolation.

Four test groups were removed because their whole subject was the deleted
surface, not because they became inconvenient. The enum membership and value
tests asserted the shape of two enums that no longer exist. The instantiation
override tests exercised the `severity` and `recovery_action` constructor
keywords, which no longer exist. The class-level defaults test asserted each
subclass's declared severity and recovery action, which no longer exist. Its
parametrized sibling asserting that the constructor message survives was dropped
with it, because once the base defines no `__init__` that assertion restates the
interpreter's own behaviour for ten classes that override nothing. One test in
the raise-and-catch group asserted the two attributes survived a raise; it was
narrowed rather than deleted, to assert that the MESSAGE survives a real raise
and catch, which is live behaviour and is the property this Step's deletion of
the base constructor could plausibly have broken. The public-surface tests kept
their guard and dropped only the two withdrawn names.

`VaultspecError` gained `__slots__ = ()` as a consequence of losing its state,
matching every sibling in the module including the other base class. This does
not remove the instance dictionary, since the built-in exception base supplies
one regardless; it is the declaration the module uses to say a class adds no
attributes of its own.
