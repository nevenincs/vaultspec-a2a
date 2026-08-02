"""Live proof that a provider lane completes a REAL web retrieval end to end.

The completed-retrieval standard, stated once and applied per lane: a lane earns
its web-grounding activation only when a real autonomous run has reached the open
web, and the material it fetched has landed in BOTH channels the citation design
declares - checkpointed state as a typed web locator, and the proposed research
document's body as a disclosed source. A surfaced tool name, an allowlist entry, a
parsed config, or a model saying it searched are none of them retrievals, and this
module is deliberately unable to pass on any of them.

Not a second driver. It reuses the standing pw7 acceptance harness exactly as the
floor and semantic proofs do (``test_tool_cores_floor_live``): ``_reachable_stack``
for the infra gate, ``AcceptanceHarness`` for token minting and run-start against
the live ``vaultspec-adr-research`` preset. What it adds is the retrieval evidence
and a NON-materializing observation - the run is watched only until that evidence
lands in checkpointed state and is then cancelled, so no verdict is ever given, no
proposal is ever applied, and the engine vault is asserted byte-unchanged.

Where the observation deliberately STOPS is worth stating, because it is a scoping
decision rather than a shortcut. It stops at the evidence, not at a queued proposal
and not at a completed run. Everything after the evidence - the inner document-review
loop, the later phases, the human gates - is governed by other Steps and turns on
judgements about document quality that have nothing to do with web grounding, so
requiring any of it here would make this lane's proof hostage to an unrelated
verdict. The disclosure obligation is asserted DIRECTLY against the proposed body
instead, which is the stronger reading of it anyway: inferring disclosure from a
submit that was not refused would only ever have been circumstantial.

**The unguessable-token device.** A model can produce a plausible URL from recall,
so citing one proves nothing. The proof therefore keys on a value that exists only
on the live web and cannot be recalled, guessed, or derived: the 40-character SHA
of a recent commit in a public repository. The test resolves the current set of
those SHAs itself, immediately before and immediately after the run, and requires
the agent's own finding to carry one of them verbatim. A token drawn from a set
the test observed live, that the prompt never carried, can only have reached the
finding through a retrieval that actually happened. Fetching before AND after
absorbs the one benign race - a commit landing mid-run - without widening what
counts as evidence.

Three assertions, and each one fails the lane rather than softening:

* the researcher's finding reproduces a live commit SHA - the retrieval happened;
* checkpointed state carries a typed web locator (``kind`` web) for the retrieved
  URL - the run's machine-checkable evidence channel received it;
* the proposed research document body discloses that URL under a Sources heading -
  the reader-facing channel received it.

Infrastructure gate, not a masked failure (the sanctioned pw7 pattern): an absent
loopback stack reports through the external-prerequisite rule, and an unreachable
public web or a spent provider usage window reports as a truthful skip naming what
is missing - in neither case can the lane be asked to do the work. Every OTHER
terminal failure is this Step's business and fails loud, as does a run that reached
the web and then failed to cite it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from ..control.run_start_policy import required_role_ids
from ..graph.nodes.diverge import WEB_LOCATOR_KIND
from ..team.team_config import load_team_config
from .test_pw7_acceptance import (
    _GATEWAY_AUTH_HEADERS,
    _MODE_MANUAL,
    _PRESET_LIVE,
    AcceptanceCase,
    AcceptanceHarness,
    _reachable_stack,
)
from .test_tool_cores_floor_live import _snapshot_vault, _vault_write_delta

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ..conftest import ExternalPrerequisiteRule

logger = logging.getLogger(__name__)

# The retrieval target. A public, unauthenticated JSON endpoint whose newest entry
# changes continuously, so its content is unavailable to recall by construction; the
# single-item form keeps the fetched document small enough that a provider's fetch
# tool returns the SHA rather than summarising it away.
PROOF_URL = "https://api.github.com/repos/langchain-ai/langgraph/commits?per_page=1"

# The same repository's recent history, which the TEST resolves for itself to learn
# which SHAs are live right now. A wider page than the agent fetches, so a commit
# landing between the two reads is absorbed as evidence rather than read as a miss.
_LIVE_SHA_URL = (
    "https://api.github.com/repos/langchain-ai/langgraph/commits?per_page=20"
)

#: A full-length git object id as it appears in the API's ``sha`` field. Full length
#: only: an abbreviated prefix is short enough to collide with ordinary hex prose.
_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")

#: The research document's reader-facing citation surface. Matched as a heading so a
#: URL merely mentioned in passing does not discharge the disclosure obligation.
_SOURCES_HEADING_RE = re.compile(r"^#{1,6}\s*sources\b", re.IGNORECASE | re.MULTILINE)

#: The message name the research-phase writer's document body is carried under
#: (``worker/graph_lifecycle`` binds the research phase's submitter to it), so the
#: body this test reads is the same text the submitter proposed.
_RESEARCH_WRITER_MESSAGE_NAME = "synthesis"

# A live research run authors through a fan-out, a synthesis, and an inner review
# loop before its proposal queues; bound the observation so a stalled run fails loud
# rather than hanging. Deliberately generous - the failure mode this guards against
# is a hang, not slowness.
_OBSERVE_DEADLINE_SECONDS = 3600.0

#: How often checkpointed state is asked whether the evidence has landed.
_POLL_SECONDS = 15.0

#: Substrings that identify a provider USAGE-WINDOW refusal in a run's failure reason.
#: A lane whose subscription window is spent is an absent external resource, not a
#: defect in what this module proves, and the repository's rule for an absent external
#: resource is a skip that NAMES it. Kept deliberately narrow: only the provider's own
#: rate-limit vocabulary matches, so an ordinary provider error still fails loud.
_USAGE_LIMIT_MARKERS = ("rate_limit", "usage limit", "weekly limit")

JsonObject = dict[str, object]
_JSON_OBJECT = TypeAdapter(JsonObject)
_JSON_OBJECT_LIST = TypeAdapter(list[JsonObject])
_OBJECT_LIST = TypeAdapter(list[object])


@runtime_checkable
class _WriterMessage(Protocol):
    """The writer-message shape persisted by the production checkpointer."""

    @property
    def name(self) -> str | None: ...

    @property
    def content(self) -> object: ...


def _json_object(value: object, *, at: str) -> JsonObject:
    """Read an observed object or fail at the service/checkpoint boundary."""
    try:
        return _JSON_OBJECT.validate_python(value)
    except ValidationError as exc:
        raise AssertionError(f"expected JSON object at {at}: {exc}") from exc


def _json_object_list(value: object, *, at: str) -> list[JsonObject]:
    """Read an observed object list or fail at the service/checkpoint boundary."""
    try:
        return _JSON_OBJECT_LIST.validate_python(value)
    except ValidationError as exc:
        raise AssertionError(f"expected JSON object list at {at}: {exc}") from exc


def _object_list(value: object, *, at: str) -> list[object]:
    """Read an optional heterogeneous checkpoint list without widening its values."""
    if value is None:
        return []
    try:
        return _OBJECT_LIST.validate_python(value)
    except ValidationError as exc:
        raise AssertionError(f"expected list at {at}: {exc}") from exc


def _fetch_live_commit_shas() -> set[str]:
    """Return the commit SHAs currently published for the proof repository.

    The test's own read of the live web, and the sole source of what counts as
    retrieval evidence. An unreachable or rate-limited endpoint yields an empty set,
    which the caller reports as a truthful skip - the proof cannot be POSED without
    a live token, and inventing one would make the assertion prove nothing.
    """
    try:
        response = httpx.get(
            _LIVE_SHA_URL,
            timeout=20.0,
            headers={"Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        logger.warning("could not resolve live commit SHAs from %s", _LIVE_SHA_URL)
        return set()
    entries = _json_object_list(payload, at="live GitHub commit response")
    shas: set[str] = set()
    for entry in entries:
        sha = entry.get("sha")
        if isinstance(sha, str) and _SHA_RE.fullmatch(sha):
            shas.add(sha)
    return shas


def _web_grounding_case(feature: str) -> AcceptanceCase:
    """The live retrieval case: a prompt that pins the URL, the token, and the Sources.

    Autonomous by construction. The Step's standard is a real AUTONOMOUS run, and the
    mode is also what makes the observation clean: no permission interrupt parks the
    run waiting for an answer nothing in this test would give.

    No ``gate_policy`` and no ``expected_doc_kinds``: this proof observes the research
    proposal QUEUE and cancels, so it never drives a verdict and never materializes a
    document.
    """
    return AcceptanceCase(
        label="tool-cores-web-grounding-live",
        preset=_PRESET_LIVE,
        feature=feature,
        prompt=(
            "Research the current release activity of the LangGraph project, and "
            "ground the research in the live web rather than recall.\n\n"
            "Every research thread MUST do this first, before anything else:\n"
            f"1. Fetch {PROOF_URL} from the live web.\n"
            "2. Report the value of the response's `sha` field VERBATIM - the full "
            "40-character commit id, copied exactly, not abbreviated and not "
            "summarised - together with that commit's `commit.message` and "
            "`commit.author.date`.\n"
            "3. Cite the URL you fetched inline beside the value you took from it.\n\n"
            "The research document must carry a `## Sources` section listing every "
            "URL retrieved as a bare URL with its retrieval date. A claim you did "
            "not retrieve must be presented as recall, never as a retrieved fact."
        ),
        roles=tuple(required_role_ids(load_team_config(_PRESET_LIVE))),
        expected_doc_kinds=(),
        autonomous=True,
    )


def _web_locator_urls(findings: Sequence[Mapping[str, object]]) -> list[str]:
    """Return the distinct typed web-locator URLs in *findings*, first-seen order.

    Reads the finding contract's shape directly - ``{claim, locators, source_thread}``
    with a locator carrying the contract's web ``kind`` - rather than re-deriving it,
    so this observes the channel the run actually wrote instead of a copy of it.
    """
    urls: list[str] = []
    for finding in findings:
        locators: object = finding.get("locators")
        if locators is None:
            continue
        for locator in _object_list(locators, at="finding locators"):
            try:
                fields = _JSON_OBJECT.validate_python(locator)
            except ValidationError:
                continue
            if fields.get("kind") != WEB_LOCATOR_KIND:
                continue
            url = fields.get("url")
            if isinstance(url, str) and url and url not in urls:
                urls.append(url)
    return urls


def _finding_claims(findings: Sequence[Mapping[str, object]]) -> str:
    """Concatenate every finding's claim prose - the researchers' own turn output."""
    claims: list[str] = []
    for finding in findings:
        claim = finding.get("claim")
        if isinstance(claim, str):
            claims.append(claim)
    return "\n".join(claims)


def _sources_section(body: str) -> str:
    """Return the document body from its Sources heading onward, or an empty string.

    Scoped rather than whole-body so a URL that appears only in the prose does not
    satisfy the disclosure check the research template's Sources section owns.
    """
    match = _SOURCES_HEADING_RE.search(body)
    return body[match.start() :] if match else ""


def _writer_body(messages: Sequence[_WriterMessage], writer_name: str) -> str:
    """Return the last document body the research writer produced, or an empty string.

    The submitter proposes exactly this message's content (its last one, sentinel
    stripped), so reading it here reads the PROPOSED document rather than a
    reconstruction of it.
    """
    bodies = [
        str(message.content)
        for message in messages
        if getattr(message, "name", None) == writer_name
        and str(getattr(message, "content", "")).strip()
    ]
    return bodies[-1] if bodies else ""


async def _read_checkpointed_state(run_id: str) -> JsonObject:
    """Return the run's checkpointed channel values through the production checkpointer.

    Opened with :func:`..database.checkpoints.open_checkpointer`, so this reads the
    same backend the worker wrote - the run's authoritative state, not a projection of
    it. The gateway's wire snapshot deliberately does not carry the finding channel,
    which is why the evidence is read here rather than over HTTP.
    """
    from ..database.checkpoints import open_checkpointer

    async with open_checkpointer() as checkpointer:
        tuple_ = await checkpointer.aget_tuple({"configurable": {"thread_id": run_id}})
    if tuple_ is None:
        return {}
    # ``channel_values`` is declared on the checkpoint contract, so an invalid shape
    # is a broken checkpoint rather than an empty observation to silently tolerate.
    return _json_object(
        tuple_.checkpoint.get("channel_values"), at="checkpoint channels"
    )


@dataclass(frozen=True, slots=True)
class _Evidence:
    """What the run has put into the two citation channels so far.

    Read from checkpointed state on every poll rather than assembled at the end, so
    the observation stops the moment the proof is complete instead of riding the run
    through work that has nothing to do with web grounding.
    """

    claims: str
    locator_urls: list[str]
    body: str

    @property
    def complete(self) -> bool:
        """Both channels have received something worth asserting on."""
        return bool(self.locator_urls) and bool(self.body)


async def _read_evidence(run_id: str) -> _Evidence:
    """Project the run's checkpointed state onto the two citation channels."""
    state = await _read_checkpointed_state(run_id)
    raw_findings = state.get("research_findings")
    findings = (
        []
        if raw_findings is None
        else _json_object_list(raw_findings, at="checkpoint research findings")
    )
    messages = [
        message
        for message in _object_list(state.get("messages"), at="checkpoint messages")
        if isinstance(message, _WriterMessage)
    ]
    return _Evidence(
        claims=_finding_claims(findings),
        locator_urls=_web_locator_urls(findings),
        body=_writer_body(messages, _RESEARCH_WRITER_MESSAGE_NAME),
    )


def _is_usage_limit(failure_reason: str) -> bool:
    """Whether *failure_reason* is the provider's usage window being spent."""
    lowered = failure_reason.lower()
    return any(marker in lowered for marker in _USAGE_LIMIT_MARKERS)


@pytest.mark.service
@pytest.mark.resource("loopback-stack")
@pytest.mark.resource("claude-cli-lane")
@pytest.mark.asyncio
@pytest.mark.timeout(_OBSERVE_DEADLINE_SECONDS + 600.0)
async def test_claude_lane_completes_a_real_web_retrieval(
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """Live: an autonomous Claude run retrieves from the web and cites it both ways.

    The Claude lane's completed-retrieval proof. Zero vault writes: the run is
    observed only until the evidence lands in checkpointed state, then cancelled with
    nothing ever applied, and a before / after snapshot of the engine workspace
    asserts no document changed.
    """
    stack = _reachable_stack()
    if stack is None:
        external_prerequisite.absent("loopback-stack")
    gateway_url, engine_base_url, engine_bearer, vault_root = stack

    shas_before = _fetch_live_commit_shas()
    if not shas_before:
        pytest.skip(
            f"could not resolve live commit SHAs from {_LIVE_SHA_URL} (network "
            "unreachable or rate-limited); the completed-retrieval proof cannot be "
            "posed without a live token the prompt never carried. This is a truthful "
            "skip, not a masked failure"
        )

    feature = f"tool-cores-web-{int(time.time())}"
    case = _web_grounding_case(feature)
    harness = AcceptanceHarness(
        case=case,
        engine_base_url=engine_base_url,
        engine_bearer=engine_bearer,
        vault_root=vault_root,
        gateway_url=gateway_url,
    )

    before = _snapshot_vault(vault_root)
    evidence = _Evidence(claims="", locator_urls=[], body="")
    failure_reason = ""

    from .test_pw7_acceptance import _ResilientAuthoringClient

    async with _ResilientAuthoringClient(engine_base_url, engine_bearer) as ec:
        run_tokens = {
            role: await harness._mint(ec, f"agent:{harness.run_id}:{role}", "agent")
            for role in case.roles
        }
        reviewer_human = await harness._mint(ec, f"rev-human:{harness.run_id}", "human")
        # Manual mode is the zero-writes guarantee at its source: a queued proposal
        # waits for a human verdict this test never gives, so nothing can apply even
        # if the observation loop were to overrun its deadline.
        await harness._set_mode(ec, _MODE_MANUAL, setter_token=reviewer_human)

        # The gateway fails closed on every /v1/ route unless the caller presents
        # the service-discovery bearer the booting shell configured it with; an
        # unauthenticated client degrades to a truthful 401 rather than a run.
        async with httpx.AsyncClient(headers=_GATEWAY_AUTH_HEADERS) as hc:
            await harness._run_start(
                hc,
                run_id=harness.run_id,
                tokens=run_tokens,
                feature=feature,
                expect=201,
            )
            deadline = time.monotonic() + _OBSERVE_DEADLINE_SECONDS
            try:
                # Observe until the EVIDENCE is complete, not until the run is. What
                # this Step proves is that a retrieval reached both citation channels;
                # everything the run does afterwards - the inner quality loop, the
                # later phases, the human gates - is governed by other Steps, and
                # riding the run through it would make this proof hostage to verdicts
                # about document quality that have nothing to do with web grounding.
                while time.monotonic() < deadline:
                    evidence = await _read_evidence(harness.run_id)
                    if evidence.complete:
                        break
                    status = await harness._run_status(hc)
                    if status.get("status") in {"failed", "cancelled"}:
                        failure_reason = str(status.get("failure_reason") or "")
                        break
                    await asyncio.sleep(_POLL_SECONDS)
            finally:
                await hc.post(
                    f"{harness.gateway_url}/v1/runs/{harness.run_id}/cancel",
                    timeout=30.0,
                )

    # A run that died before the evidence landed proves nothing either way, so the
    # two causes are separated rather than reported as one failure. A spent provider
    # usage window is an ABSENT EXTERNAL RESOURCE - the lane cannot be asked to work
    # at all - and the repository's rule for that is a skip naming it. Any other
    # terminal failure is this Step's business and fails loud.
    if not evidence.complete and failure_reason:
        if _is_usage_limit(failure_reason):
            pytest.skip(
                f"the {_PRESET_LIVE!r} lane's provider refused the run on its usage "
                f"window before the evidence landed: {failure_reason}. This is a "
                "truthful skip naming an absent external resource, not a masked "
                "failure - re-run once the window resets"
            )
        pytest.fail(
            f"run {harness.run_id} went terminal before the retrieval evidence "
            f"landed: {failure_reason}"
        )

    shas_after = _fetch_live_commit_shas()
    live_shas = shas_before | shas_after

    after = _snapshot_vault(vault_root)
    delta = _vault_write_delta(before, after)

    locator_urls = evidence.locator_urls
    body = evidence.body
    sources = _sources_section(body)
    reproduced = sorted(
        sha for sha in _SHA_RE.findall(evidence.claims) if sha in live_shas
    )

    # 1. The retrieval actually happened. A live commit SHA the prompt never carried
    #    can only reach a finding by having been fetched.
    assert reproduced, (
        f"no researcher finding reproduced a live commit SHA (run {harness.run_id}); "
        f"the lane did not complete a real web retrieval. Locators recorded: "
        f"{len(locator_urls)}; live SHAs in play: {len(live_shas)}"
    )
    # 2. THAT retrieval reached the run's typed evidence channel. Keyed on the URL
    #    the token came from, not on "some locator exists": a locator for a URL this
    #    test never verified as fetched would be evidence of prose, not of reach.
    assert PROOF_URL in locator_urls, (
        f"the run reproduced a live token but checkpointed state carries no typed "
        f"{WEB_LOCATOR_KIND!r} locator for {PROOF_URL} (run {harness.run_id}); "
        f"locators recorded: {locator_urls}"
    )
    # 3. THAT retrieval reached the reader-facing channel, in the section that owns
    #    it, AND the retrieved fact itself survived into the proposed document - so
    #    the disclosure is of something the document actually relies on rather than a
    #    URL parked in a list.
    assert body, (
        f"the research writer produced no document body to inspect (run "
        f"{harness.run_id}); the Sources-disclosure half of the proof is unobservable"
    )
    assert sources, (
        f"the proposed research document carries no Sources heading (run "
        f"{harness.run_id}); a retrieved URL has nowhere disclosed to live"
    )
    assert PROOF_URL in sources, (
        f"the proposed research document's Sources section omits the URL the verified "
        f"retrieval came from ({PROOF_URL}) (run {harness.run_id})"
    )
    assert any(sha in body for sha in reproduced), (
        f"the proposed research document discloses {PROOF_URL} but carries none of "
        f"the retrieved values {reproduced} it was retrieved for (run "
        f"{harness.run_id}); the citation is decorative"
    )
    # Deliberately reported, NOT asserted. Whether EVERY retrieved URL is disclosed is
    # the submitter's structural refusal - a different obligation, owned and proven
    # where that refusal lives, and enforced at submit rather than here. Asserting it
    # in this module would restate another Step's claim over URLs whose retrieval this
    # test never verified, turning a proof about the LANE's reach into a judgement
    # about one writer's diligence. Observed live: a run can and does leave a locator
    # undisclosed, which is exactly the case that refusal exists to route to revision.
    residual = [url for url in locator_urls if url not in sources]
    if residual:
        logger.warning(
            "run %s left retrieved URL(s) undisclosed in the proposed body: %s; the "
            "submitter's disclosure refusal is what routes this to revision",
            harness.run_id,
            residual,
        )
    assert delta == {"created": [], "modified": [], "deleted": []}, (
        f"the retrieval proof must not write to .vault, but the run changed it: {delta}"
    )


def test_proof_case_pins_the_url_the_token_and_the_sources_obligation() -> None:
    """Stack-free guard: the live case is well-posed and cannot pass on recall.

    Pins the three properties the live assertion depends on - the exact URL is in the
    prompt, the run is autonomous, and no gate policy or expected document set could
    drive a materialization - plus the one that makes the evidence hallucination-proof:
    the prompt must NOT carry any 40-character hex token, or an agent echoing the
    prompt would satisfy the retrieval assertion without retrieving.
    """
    case = _web_grounding_case("tool-cores-web-guard")
    assert PROOF_URL in case.prompt
    assert "Sources" in case.prompt
    assert case.preset == _PRESET_LIVE
    assert case.autonomous is True
    assert case.gate_policy == {}
    assert case.expected_doc_kinds == ()
    assert not _SHA_RE.findall(case.prompt)


def test_web_locator_urls_reads_the_finding_contract_shape() -> None:
    """Stack-free guard: only typed web locators count, deduped and in first-seen order.

    An internal ``path:line`` locator sharing the list, a malformed entry, and a
    duplicate URL must all be ignored; if any of them counted, the live assertion
    could pass on evidence that is not a web retrieval.
    """
    findings = [
        {
            "claim": "first",
            "locators": [
                {"kind": "code", "path": "src/mod.py", "line": 3},
                {"kind": WEB_LOCATOR_KIND, "url": "https://example.test/a"},
                "not-a-locator",
            ],
            "source_thread": "t1",
        },
        {
            "claim": "second",
            "locators": [
                {"kind": WEB_LOCATOR_KIND, "url": "https://example.test/a"},
                {"kind": WEB_LOCATOR_KIND, "url": "https://example.test/b"},
            ],
            "source_thread": "t2",
        },
        {"claim": "third", "locators": None, "source_thread": "t3"},
    ]
    assert _web_locator_urls(findings) == [
        "https://example.test/a",
        "https://example.test/b",
    ]
    assert _web_locator_urls([]) == []


def test_json_reader_rejects_a_non_object_github_commit_payload() -> None:
    """The live GitHub response must be an object list, never a scalar object."""
    with pytest.raises(AssertionError, match="live GitHub commit response"):
        _json_object_list({"sha": "not a list"}, at="live GitHub commit response")


def test_json_reader_rejects_malformed_checkpoint_channels() -> None:
    """Checkpoint channels must remain an object before evidence is projected."""
    with pytest.raises(AssertionError, match="checkpoint channels"):
        _json_object(["not checkpoint channels"], at="checkpoint channels")


def test_json_reader_rejects_malformed_checkpoint_findings() -> None:
    """Research findings must remain a list of objects at the checkpoint boundary."""
    with pytest.raises(AssertionError, match="checkpoint research findings"):
        _json_object_list(["not a research finding"], at="checkpoint research findings")


def test_json_reader_rejects_malformed_checkpoint_messages() -> None:
    """The heterogeneous message channel must still be a list."""
    with pytest.raises(AssertionError, match="checkpoint messages"):
        _object_list({"content": "not a message list"}, at="checkpoint messages")


def test_web_locator_urls_rejects_a_non_list_locator_collection() -> None:
    """Only individual malformed locators are tolerant; their collection is not."""
    findings: list[dict[str, object]] = [
        {"claim": "grounded", "locators": {"url": PROOF_URL}}
    ]
    with pytest.raises(AssertionError, match="finding locators"):
        _web_locator_urls(findings)


def test_sources_section_is_scoped_to_the_sources_heading() -> None:
    """Stack-free guard: a URL in prose alone does not discharge the disclosure."""
    prose_only = "# research\n\nWe consulted https://example.test/a while thinking.\n"
    assert _sources_section(prose_only) == ""
    disclosed = (
        "# research\n\nBody prose citing https://example.test/a inline.\n\n"
        "## Sources\n\n- https://example.test/a (retrieved 2026-08-01)\n"
    )
    section = _sources_section(disclosed)
    assert "https://example.test/a" in section
    assert "Body prose" not in section


def test_evidence_is_complete_only_when_both_channels_received_something() -> None:
    """Stack-free guard: one channel alone never ends the observation.

    The loop breaks on completeness, so a completeness predicate satisfied by a
    locator with no document - or a document with no locator - would end the
    observation early and then assert against half a proof.
    """
    assert not _Evidence(claims="c", locator_urls=[], body="").complete
    assert not _Evidence(claims="c", locator_urls=["https://x.test"], body="").complete
    assert not _Evidence(claims="c", locator_urls=[], body="# doc").complete
    assert _Evidence(claims="c", locator_urls=["https://x.test"], body="# doc").complete


def test_usage_limit_classification_is_narrow() -> None:
    """Stack-free guard: only a spent usage window skips; every other failure fails.

    The skip branch is the one place this module can decline to prove anything, so
    the predicate that opens it must not admit ordinary provider or graph errors -
    that is exactly how a real regression would come to report as an absent
    prerequisite.
    """
    assert _is_usage_limit(
        "ACP Error [-32603]: You've hit your weekly limit | Data: "
        "{'errorKind': 'rate_limit'}"
    )
    assert _is_usage_limit("provider refused: usage limit reached")
    assert not _is_usage_limit("")
    assert not _is_usage_limit(
        "WorkerExecutionError: worker='research_review' model=AcpChatModel messages=8"
    )
    assert not _is_usage_limit("ACP Error [-32603]: transport closed unexpectedly")


def test_writer_body_returns_the_last_body_the_research_writer_produced() -> None:
    """Stack-free guard: the body read is the writer's LAST one, and only the writer's.

    A revision loop leaves several writer messages in state and the submitter proposes
    the last; reading an earlier one - or another agent's message - would inspect a
    document that was never proposed.
    """

    class _Message:
        def __init__(self, name: str, content: str) -> None:
            self.name = name
            self.content = content

    messages = [
        _Message("vaultspec-doc-reviewer", "REVISION REQUIRED"),
        _Message(_RESEARCH_WRITER_MESSAGE_NAME, "first draft"),
        _Message("vaultspec-doc-reviewer", "PASS"),
        _Message(_RESEARCH_WRITER_MESSAGE_NAME, "revised draft"),
    ]
    assert _writer_body(messages, _RESEARCH_WRITER_MESSAGE_NAME) == "revised draft"
    assert _writer_body([], _RESEARCH_WRITER_MESSAGE_NAME) == ""
