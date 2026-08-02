---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:8fef5760f67c1bc27f520bf8608df9668d874a590ce779ee81704f286be2f423'
step_id: 'S28'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Prove throttled and overloaded conditions retry under the existing backoff policy

## Scope

- `src/vaultspec_a2a/graph/tests/test_compiler.py`

## Description

- Build one real provider failure per condition member, each from the wire shape
  of the lane that actually emits that member, resolved through that lane's own
  mapper.
- Write out the specified attempt count for all nine members as a literal table
  rather than reading the production set back.
- Compile a real one-node graph whose node wraps and chains its provider failure
  the way the worker node does, and count the attempts the node body makes.
- Sweep every member through that graph and assert the real attempt count.
- Run one throttled case under the untouched production policy and assert its
  configured first interval actually elapsed.
- Drive the lane retry hint in both directions through the same graph.
- Assert that compilation attaches the proven policy object to every model-backed
  node.

## Outcome

Four assertions, and each covers a way the other three can be fooled.

The exhaustive sweep drives every one of the nine members through a real compiled
graph and counts what the node body actually did: three attempts for throttled,
overloaded and unreachable, exactly one for the six that are refused. Both halves
are load-bearing. Without the retrying members the sweep cannot show the policy
fires at all; without the refusing ones it cannot distinguish a classifier from a
policy that retries everything, which would spend a user's quota on failures no
retry can fix.

The expected counts are spelled out as a literal table rather than derived from
the production set. Reading the set back would have made the table agree with the
code by construction and pass however the code was mutated - the precise shape of
a test that camouflages the thing it was written to protect.

The failures themselves are not hand-built either. Each member is produced from a
wire-shaped payload of the lane that emits it, passed through that lane's real
mapper, so a mapping change moves these cases with it rather than leaving them
asserting a member no lane still produces. Six come from the ACP lane's error
kinds and three - unreachable, exhausted usage, exhausted budget - from the Codex
lane's own turn-error builder, which is the only wire that names them. The sweep
additionally asserts that each constructed failure really carries the member its
case is about, so a mapping change cannot leave nine cases silently exercising
one condition.

The node wraps its provider failure and chains it, which is the shape the worker
node produces in production and therefore the shape the classifier has to unwrap.
Testing the bare exception would have left the wrapper path - the only path a
real provider fault takes - unproven.

The fourth assertion closes the gap that made this Phase necessary in the first
place. A behavioural test still describes only a policy OBJECT; it would pass
unchanged with that object attached to no node at all, which is exactly the state
the retry policy was in for the whole life of the provider adapters. So
compilation is driven for real and every model-backed node is checked to carry
the same policy object the behavioural cases exercised.

That fourth assertion shipped too narrow and was widened after review. It first
iterated only the resolved agent configurations, which reached three of the
eleven attachment sites; a review mutation that detached the other eight - the
supervisor, the fan-out researcher, and the six document phase machine nodes -
left the whole file green. It now compiles all four topologies and asserts the
inverse property: every node carrying NO policy must be a declared structural
node, a mount step, a human gate, a submit or a fan-out dispatch. The polarity is
deliberate. A list of nodes that should carry the policy is a second table that
silently stops covering whatever is added next, which is how eight sites came to
be unasserted in the first place; stated inversely, a newly added model-backed
node fails the assertion until someone decides which side of the line it is on.
The same detach-the-non-worker-sites mutation now fails it.

Bounding the backoff was a deliberate trade, and it is split rather than
uniform. The sweep runs the production policy with its two timing fields replaced
and nothing else - the classifier and the attempt ceiling are carried over
verbatim from the shipped object - which takes nine cases from roughly fourteen
seconds of real sleeping to about forty milliseconds. That leaves the shipped
intervals unexercised, so one throttled case runs the untouched production object
and asserts that at least the configured first interval elapsed across its three
attempts. Anything faster would mean no real backoff ran. That case costs about
two seconds, which is the honest price of proving the wait a throttled provider
actually gets.

Mutation check, four mutations, each reverted before the next:

- Every condition made non-retryable: the three retrying cases and the shipped
  backoff case failed; the six refusing cases and the hint case still passed,
  correctly, since neither depends on the set having members.
- Every condition made retryable: all six refusing cases failed.
- The lane hint consulted and its answer discarded: the hint case failed.
- The policy detached from every node at compilation: the attachment case failed.
  This is the mutation that reproduces the original defect exactly, and it is the
  one a purely behavioural test would have passed.

The file was restored from a byte copy after each mutation and after the last;
the working tree reports the file unmodified against its commit.

Verification: `ruff format` left both files unchanged and `ruff check` passes on
this package. Whole-tree `ruff check src` and `ty check` each report findings
only in three modules owned by other lanes - the gateway internal test, the
desktop ACP profile test named as known-failing, and a newly added failure
scenario preset test - and none in the graph package. The graph suite passed 318
tests, 2 deselected, in 124s.

## Notes

The retry hint case is proved on the Codex lane only, because that is the only
served lane whose wire carries the flag. This is a property of the lanes rather
than a coverage gap, and the ACP lane's silence is itself covered: every ACP case
in the sweep resolves by condition alone, which is what an absent hint must do.

One asymmetry surfaces from the sweep and is worth reading as a product fact
rather than a test artefact. Exhausted usage is proved non-retrying here through
the lane that names it. The other served lane cannot separate an exhausted window
from a rate refusal and maps both to the throttled member, so the same real
condition WILL be retried there. That follows from the vocabulary's documented
information limit, and the cost is two extra refused requests.
