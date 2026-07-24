---
tags:
  - '#adr'
  - '#codebase-health'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - '[[2026-07-19-codebase-health-audit]]'
  - '[[2026-07-19-codebase-health-plan]]'
  - '[[2026-07-19-codebase-health-adr]]'
---

# `codebase-health` adr: `the authenticated pairing verdict governs worker adoption under the armed profile` | (**status:** `accepted`)

## Problem Statement

The audit's high finding authenticated-pairing-verdict-not-enforced
establishes that the fail-closed pairing classifier and its eviction
authorization are implemented and unit-proven but have no production caller:
the worker advertises its paired gateway lifetime and spawn generation on its
health surface, yet every real adoption decision gates on the weaker declared
gateway-URL signal, which by design treats blank evidence as a same-gateway
match. The stricter policy the codebase built is therefore not the policy
enforced, a plain-health squatter would be adopted where the classifier would
refuse it, and the plan's real-process pairing proofs cannot honestly close.
The audit marks the wiring a policy decision, not a mechanical rewrite; this
record makes that decision. Its scope is worker-to-gateway provenance only -
the audit's other owed decisions (cross-store deletion, process ownership,
attach authentication, event allowlist) remain owed elsewhere.

## Considerations

- The armed desktop profile is the shipped product surface and already the
  established strict/fail-closed axis: it owns its worker exclusively, seats
  it in OS containment, and never shares its private worker port by design.
- Development and Compose stacks predate pairing evidence: workers managed by
  the dev process registry or Compose legitimately carry no lifetime claim,
  and disowning them would regress every working dev topology - the exact
  no-regression concern that shaped the lenient gateway-URL signal.
- Blank evidence is precisely what a foreign or unmanaged process looks like;
  under the product profile, silence must not read as ownership.
- Eviction is a hard kill of another process; the classifier's authorization
  already confines it to an armed gateway reclaiming its own prior
  generation.
- The classifier needs the gateway's current spawn generation to rule; only
  the worker spawner owns that counter, so enforcement must thread it to the
  adoption seams rather than minting a second counter.

## Considered options

- **Profile-split enforcement: the verdict is the adoption authority when the
  desktop profile is armed; the legacy gateway-URL signal stays for unarmed
  profiles - chosen.** Product gets the authenticated guarantee; dev/Compose
  keep working unchanged.
- **Classifier supersedes the gateway-URL check everywhere - rejected.**
  Breaks every registry- and Compose-managed worker (all UNIDENTIFIED),
  forcing pairing-evidence plumbing through externally-owned spawn paths for
  no product gain.
- **Keep the lenient signal everywhere and retire the classifier - rejected.**
  Accepts the audited hazard permanently: any process answering health on the
  private worker port with silence or an echoed URL is adopted and dispatched
  to.

## Constraints

- Adoption and eviction must share one verdict from one health read; deciding
  eviction on a re-fetch would race the classification it authorizes.
- An armed gateway that cannot adopt must fail loud and leave the squatter
  untouched: a foreign worker may be serving another gateway's live runs, and
  an unidentified one is not provably anyone's to kill.
- A failed authorized eviction must surface as a conflict without adoption -
  spawning onto a port a surviving process still serves would hand readiness
  probes the wrong worker.
- The unarmed paths must remain byte-for-byte behavior-compatible.

## Implementation

The adoption readiness seam becomes profile-split: under the armed profile it
fetches the worker's health once, classifies the reported lifetime and
generation against the gateway's own lifetime identity and the spawner's
current generation, and accepts only the owned verdict; unarmed it keeps the
declared gateway-URL comparison. The armed spawn path, which previously
spawned unconditionally, gains the same single-read gate before binding: an
owned worker is adopted, a prior-generation worker is evicted only under the
classifier's eviction authorization and the spawn refuses on a failed
eviction, and a foreign or unidentified occupant refuses the spawn loudly
with no eviction. The spawner threads its generation counter into every
adoption call. Real-process proofs cover the plain-health squatter, the
blank-evidence squatter, the legacy URL-echo squatter, and the two-gateways-
one-worker foreign refusal.

## Rationale

The profile split wins because it puts the strict policy exactly where the
threat and the guarantee live - the product's privately-owned worker - while
costing nothing in the environments whose workers legitimately lack evidence.
The alternatives either universalize breakage or codify the audited hazard.
The classifier and its eviction authorization already encode the correct
fail-closed semantics with full unit coverage; this record only ends their
dead-code status.

## Consequences

- The audited adoption hazard closes on the product surface: silence, echoed
  URLs, and foreign lifetimes no longer authorize adoption where it matters.
- An armed gateway confronted with an unremovable or foreign occupant now
  fails loud instead of degrading into dispatch-to-stranger; operators see a
  conflict, not silent cross-wiring.
- Dev and Compose behavior is unchanged, so the lenient signal survives
  there; the audit's remaining provenance-adjacent findings (Compose profile
  regression proof, eviction-failure conflict proof) close against this
  policy as their subjects land.
- The plan's real-process pairing proofs become honestly closable and are
  delivered with the wiring.
