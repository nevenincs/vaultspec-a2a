"""Live proof that the Codex lane really retrieves from the web, and only when told to.

The Codex lane delivers web grounding through configuration rather than through an
allowlistable tool name: the per-run ``CODEX_HOME`` carries a top-level
``web_search`` key, and that key is the entire activation surface. Nothing about
that can be proven by inspecting a prompt. The tool's own ``debug prompt-input``
output is byte-identical across all four postures, because search is executed
server-side and never reaches the model-visible prompt input, so configuration,
handshake and prompt-inspection coverage are insufficient *by construction* here
and not merely by the project's completed-work standard. Only a real turn that
performs a real retrieval settles it.

What this module drives, all of it production code:

* the per-run config home is built by :func:`build_codex_config_home` from the
  real harness registry specs, so the emitted document has the same shape a real
  run gets - the posture key ahead of an ``[mcp_servers.*]`` table, where TOML
  binding rules make placement load-bearing;
* the subprocess is spawned by :func:`spawn_acp_process` and driven over
  :class:`_CodexAppServerClient`, the same JSON-RPC client the chat model uses;
* the thread is opened with the chat model's OWN declared approval policy and
  sandbox defaults, read off the model class rather than restated here, so this
  proof cannot drift away from the posture production actually runs under;
* the retrieved prose is carried into the finding contract by the real research
  producer and the real researcher node, so the evidence lands where a run's
  checkpointed state would carry it.

Why the turn is driven at the protocol level rather than through
``CodexChatModel.astream``: the chat model consumes only assistant-message deltas
and drops every other notification, so the ``webSearch`` items that PROVE a
retrieval happened are invisible through it. This module is an observation
harness over the production protocol client, in the same spirit as the SSE
observation used by the deterministic floor proof - not a second turn driver, and
never a substitute for the production chain, which is exercised separately below.

**The control is what makes the live result mean anything.** A search observed
under the live posture proves only that Codex searched; run with the posture set
to ``disabled`` the same prompt must produce NO search at all. Both are driven
here, so a green run says the configuration caused the reach rather than merely
accompanying it.

**The retrieved fact is chosen to be unrecallable.** The turn is asked for the
current released version of a package that publishes on most working days, and
the expected value is read from the package index by this test at run time,
before and after the turn (either is accepted, so a release landing mid-run is
not a failure). A model answering from weights cannot produce today's value, so a
match is evidence of retrieval rather than of recall. It is evidence of a LIVE
retrieval specifically: driven with the posture set to cached, the same turn
answered the previous day's release - a real retrieval from a provider-maintained
index, and still stale, which is the freshness divergence the served posture
exists to close.

Re-arm (one command):

    uv run --no-sync pytest -m service \\
        src/vaultspec_a2a/service_tests/test_codex_web_grounding_live.py

Service-marked, so deselected from the default suite. Absent prerequisites - no
Codex CLI, no Codex session credential, no outbound network - skip naming exactly
what is missing; when they are present every assertion is fail-loud.
"""

from __future__ import annotations

import asyncio
import tomllib
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx
import pytest
from langchain_core.messages import HumanMessage

from ..graph.compiler import _make_research_producer
from ..graph.enums import MODEL_MAP, Model, Provider
from ..graph.nodes.diverge import WEB_LOCATOR_KIND, create_researcher_node
from ..providers._acp_mcp import codex_mcp_server_specs
from ..providers._codex_config_home import (
    SERVED_WEB_SEARCH_MODE,
    build_codex_config_home,
    cleanup_codex_config_home,
    resolve_codex_web_search_mode,
)
from ..providers._json_contract import JsonObject, json_list, json_object, json_text
from ..providers._subprocess import spawn_acp_process
from ..providers.codex_chat_model import (
    _CAPABILITIES,
    _CLIENT_INFO,
    CodexChatModel,
    _CodexAppServerClient,
)
from ..providers.factory import ProviderFactory
from ..providers.lane_admission import is_web_lane_proven
from ..utils.enums import CodexWebSearchMode
from ..workspace.environment import resolve_env_vars

if TYPE_CHECKING:
    from ..conftest import ExternalPrerequisiteRule
    from ..thread.state import TeamState

# The harness servers a real research run declares. Included so the rendered
# config carries an ``[mcp_servers.*]`` table BELOW the posture key: a bare key
# emitted after a table header would parse cleanly as an option of that table and
# mean something else entirely, so the live turn must run against the document
# shape production emits, not a stripped one.
_HARNESS_SERVERS = ("vaultspec-rag",)

# The retrieval target. A package that publishes on most working days, served by
# an index that answers a plain GET, so this test can compute the expected value
# itself instead of trusting a value written into it.
_SOURCE_URL = "https://pypi.org/pypi/boto3/json"
_SOURCE_HOST = "pypi.org"

_PROMPT = (
    "Use your web tool to OPEN the exact URL "
    f"{_SOURCE_URL} and report the exact value of its info.version field, "
    "verbatim. Read that document itself: a search-result snippet about the "
    "package is not acceptable, because snippets are indexed and can be stale. "
    "Do not run any shell command, and do not answer from memory. "
    "Reply with that version string on a line of its own, followed by the line: "
    f"SOURCE: {_SOURCE_URL}"
)

# A codex turn that searches takes tens of seconds; bound the observation so a
# stalled turn fails loud rather than hanging the suite.
_TURN_DEADLINE_SECONDS = 120.0
_RPC_TIMEOUT_SECONDS = 120.0

# How many live turns the retrieval is given to produce the current value.
#
# NOT a tolerance on the claim, and it cannot green-wash a lane that has lost its
# reach: an attempt counts only when the server reported a real search AND the
# answer carries a value the index is serving right now, and a lane whose search
# is off produces neither in any number of attempts. What it absorbs is the model
# choosing its own tool path - observed live, a turn occasionally answers from an
# indexed search snippet instead of opening the document it was pointed at, and
# the stale value that yields is precisely what the freshness assertion is built
# to reject. Retrying that is retrying a nondeterministic route to the same fact,
# not retrying until an assertion relents.
_LIVE_ATTEMPTS = 2

# Notification methods that would indicate the run was asked to approve
# something. Under the never-approval policy none may appear.
_APPROVAL_TOKENS = ("approval", "permission")


@dataclass(slots=True)
class _TurnObservation:
    """Everything one observed Codex turn said, plus the config it ran under."""

    config_toml: str
    frames: list[JsonObject] = field(default_factory=list)
    text: str = ""
    status: str = ""
    # The values the index was serving around this turn - read live, never
    # written into this module, and carried on the observation so the assertion
    # compares against what was true while the turn ran.
    current_versions: set[str] = field(default_factory=set)

    def web_searches(self) -> list[JsonObject]:
        """The completed ``webSearch`` items the server reported for this turn.

        Server-emitted, not model prose: the item carries the query the tool ran,
        the action it took, and the results it got back. This is the frame class
        that distinguishes a retrieval from a claim of one.
        """
        items: list[JsonObject] = []
        for frame in self.frames:
            if frame.get("method") != "item/completed":
                continue
            params = json_object(frame.get("params"), at="item-completed params")
            item = json_object(params.get("item"), at="item-completed item")
            if item.get("type") == "webSearch":
                items.append(item)
        return items

    def approval_frames(self) -> list[str]:
        """Notification methods mentioning approval or permission, if any."""
        return [
            method
            for frame in self.frames
            if isinstance(method := frame.get("method"), str)
            and any(token in method.lower() for token in _APPROVAL_TOKENS)
        ]


def _urls_of(item: JsonObject) -> list[str]:
    """Every URL a completed ``webSearch`` item reports having reached."""
    urls: list[str] = []
    action_value = item.get("action")
    if action_value is not None:
        action = json_object(action_value, at="web-search action")
        action_url = action.get("url")
        if isinstance(action_url, str):
            urls.append(action_url)
    results_value = item.get("results")
    if results_value is not None:
        for raw_result in json_list(results_value, at="web-search results"):
            result = json_object(raw_result, at="web-search result")
            result_url = result.get("url")
            if isinstance(result_url, str):
                urls.append(result_url)
    return urls


def _host_matches(url: str) -> bool:
    """True when *url* is served by the retrieval target's host."""
    host = (urlsplit(url).hostname or "").lower()
    return host == _SOURCE_HOST or host.endswith(f".{_SOURCE_HOST}")


def _published_version() -> str:
    """Read the package index for the current released version.

    Computed here rather than written into the test: an expected value copied
    into the source would go stale into a false failure, and - worse - could not
    distinguish retrieval from recall, which is the whole point of the check.
    """
    response = httpx.get(_SOURCE_URL, timeout=30.0, headers={"Accept": "*/*"})
    response.raise_for_status()
    payload = json_object(response.json(), at="package index response")
    info = json_object(payload.get("info"), at="package index response.info")
    version = json_text(info.get("version"), at="package index response.info.version")
    if not version.strip():
        raise ValueError(f"{_SOURCE_URL} served no usable info.version")
    return version


def test_package_index_reader_rejects_a_non_object_payload() -> None:
    """The live index reader must not reinterpret an array as package metadata."""
    with pytest.raises(TypeError, match="package index response"):
        json_object([], at="package index response")


def test_completed_web_search_reader_rejects_non_object_params() -> None:
    """A completed-item notification needs an object params envelope."""
    observation = _TurnObservation(
        config_toml="",
        frames=[{"method": "item/completed", "params": []}],
    )
    with pytest.raises(TypeError, match="item-completed params"):
        observation.web_searches()


def test_web_search_url_reader_rejects_a_non_list_results_field() -> None:
    """A web-search result collection must remain a JSON array."""
    with pytest.raises(TypeError, match="web-search results"):
        _urls_of({"results": {"url": _SOURCE_URL}})


def _record_observation_frame(observation: _TurnObservation, frame: JsonObject) -> bool:
    """Record one app-server notification; return whether it ends the observation."""
    observation.frames.append(frame)
    method = frame.get("method")
    params = json_object(frame.get("params"), at="frame.params")
    if method == "item/agentMessage/delta":
        delta = params.get("delta")
        if isinstance(delta, str):
            observation.text += delta
        return False
    if method == "turn/completed":
        turn = json_object(params.get("turn"), at="params.turn")
        observation.status = str(turn.get("status"))
        for raw in json_list(turn.get("items"), at="turn.items"):
            item = json_object(raw, at="turn.items[]")
            if item.get("type") == "agentMessage" and item.get("text"):
                observation.text += f"\n{json_text(item['text'])}"
        return True
    if method == "error":
        observation.status = "error"
        return True
    return False


def test_observation_reader_rejects_a_missing_or_falsy_frame_params() -> None:
    """Every app-server notification must carry an object ``params`` envelope."""
    frames: list[JsonObject] = [
        {"method": "item/agentMessage/delta"},
        {"method": "item/agentMessage/delta", "params": []},
    ]
    for frame in frames:
        with pytest.raises(TypeError, match=r"frame\.params"):
            _record_observation_frame(_TurnObservation(config_toml=""), frame)


def test_observation_reader_rejects_a_missing_or_falsy_completed_turn() -> None:
    """A terminal turn notification must carry its object result."""
    frames: list[JsonObject] = [
        {"method": "turn/completed", "params": {}},
        {"method": "turn/completed", "params": {"turn": []}},
    ]
    for frame in frames:
        with pytest.raises(TypeError, match=r"params\.turn"):
            _record_observation_frame(
                _TurnObservation(config_toml=""),
                frame,
            )


def test_observation_reader_rejects_a_missing_or_falsy_completed_items() -> None:
    """A completed turn must carry the item list used for final text evidence."""
    frames: list[JsonObject] = [
        {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
        {
            "method": "turn/completed",
            "params": {"turn": {"status": "completed", "items": {}}},
        },
    ]
    for frame in frames:
        with pytest.raises(TypeError, match=r"turn\.items"):
            _record_observation_frame(
                _TurnObservation(config_toml=""),
                frame,
            )


async def _observe_turn(
    prompt: str, mode: CodexWebSearchMode, cwd: Path
) -> _TurnObservation:
    """Drive one real Codex turn under *mode* and return everything it emitted.

    The handshake sequence mirrors the chat model's own (initialize, initialized,
    thread/start, turn/start) because it IS the protocol; what differs is only
    that every notification is retained rather than filtered down to assistant
    deltas.

    The approval policy and sandbox are read off :class:`CodexChatModel`'s
    declared defaults so this proof asserts the posture production runs under and
    cannot silently diverge from it.
    """
    fields = CodexChatModel.model_fields
    approval_policy = fields["approval_policy"].default
    sandbox = fields["sandbox"].default

    env = resolve_env_vars(cwd)
    home = build_codex_config_home(
        codex_mcp_server_specs(list(_HARNESS_SERVERS)),
        Path.home() / ".codex",
        web_search=mode,
    )
    observation = _TurnObservation(
        config_toml=(home / "config.toml").read_text(encoding="utf-8")
    )
    env["CODEX_HOME"] = str(home)
    client: _CodexAppServerClient | None = None
    try:
        process = await spawn_acp_process(
            ["codex", "app-server"], env, str(cwd), use_exec=False, metadata={}
        )
        client = _CodexAppServerClient(process, metadata={})
        await asyncio.wait_for(
            client.request(
                "initialize",
                {"clientInfo": _CLIENT_INFO, "capabilities": _CAPABILITIES},
            ),
            timeout=_RPC_TIMEOUT_SECONDS,
        )
        client.notify("initialized", {})
        thread = await asyncio.wait_for(
            client.request(
                "thread/start",
                {
                    "cwd": str(cwd),
                    "model": MODEL_MAP[Provider.CODEX][Model.LOW],
                    "approvalPolicy": approval_policy,
                    "sandbox": sandbox,
                    "ephemeral": True,
                    "experimentalRawEvents": False,
                },
            ),
            timeout=_RPC_TIMEOUT_SECONDS,
        )
        thread_id = json_text(
            json_object(thread["thread"], at="thread")["id"], at="thread.id"
        )
        await asyncio.wait_for(
            client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": prompt, "text_elements": []}],
                    "model": MODEL_MAP[Provider.CODEX][Model.LOW],
                    "effort": None,
                    "outputSchema": None,
                },
            ),
            timeout=_RPC_TIMEOUT_SECONDS,
        )
        while True:
            frame = await asyncio.wait_for(
                client.notifications.get(), timeout=_TURN_DEADLINE_SECONDS
            )
            if _record_observation_frame(observation, frame):
                return observation
    finally:
        if client is not None:
            await client.aclose()
        cleanup_codex_config_home(home)


def _require_codex(rule: ExternalPrerequisiteRule) -> None:
    """Skip unless the Codex CLI is installed AND carries a session credential."""
    rule("codex-cli")
    if not (Path.home() / ".codex" / "auth.json").is_file():
        rule.absent("codex-cli", "no ~/.codex/auth.json; run 'codex login'")


@pytest.fixture(scope="module")
def published_version(external_prerequisite: ExternalPrerequisiteRule) -> str:
    """The current released version, read live, or an honest skip.

    Reachability of the index is this proof's own precondition: with no outbound
    network there is nothing to retrieve, and a red test would misattribute the
    absence to the lane.
    """
    _require_codex(external_prerequisite)
    try:
        return _published_version()
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        pytest.skip(f"no outbound network to {_SOURCE_HOST} ({exc!r})")


@pytest.fixture(scope="module")
def live_turn(
    published_version: str, tmp_path_factory: pytest.TempPathFactory
) -> _TurnObservation:
    """A real Codex turn under the served (live) posture, and what it retrieved.

    The index is re-read after every attempt and both readings are accepted, so a
    release landing mid-turn is not mistaken for a stale answer. The LAST
    observation is returned when no attempt satisfies the standard, so the
    assertions below fail against real evidence rather than against a retry loop.
    """
    current = {published_version}
    observation: _TurnObservation | None = None
    for attempt in range(_LIVE_ATTEMPTS):
        cwd = tmp_path_factory.mktemp(f"codex-live-web-{attempt}")
        observation = asyncio.run(_observe_turn(_PROMPT, CodexWebSearchMode.LIVE, cwd))
        with suppress(httpx.HTTPError, ValueError, KeyError):
            current.add(_published_version())
        observation.current_versions = set(current)
        retrieved_current = any(
            version in observation.text for version in observation.current_versions
        )
        if observation.web_searches() and retrieved_current:
            break
    assert observation is not None
    return observation


@pytest.fixture(scope="module")
def disabled_turn(
    published_version: str, tmp_path_factory: pytest.TempPathFactory
) -> _TurnObservation:
    """The control: the same prompt with the posture set to disabled."""
    cwd = tmp_path_factory.mktemp("codex-disabled-web")
    return asyncio.run(_observe_turn(_PROMPT, CodexWebSearchMode.DISABLED, cwd))


@pytest.mark.service
def test_live_posture_survives_the_declared_server_table(
    live_turn: _TurnObservation,
) -> None:
    """The posture the turn ran under is a TOP-LEVEL key, not a server option.

    TOML binds a bare key to the table above it, so a ``web_search`` line emitted
    after an ``[mcp_servers.*]`` header would parse cleanly and mean an unknown
    option of that server. This asserts against the parsed document the live turn
    actually consumed, with a real declared server present.
    """
    parsed = tomllib.loads(live_turn.config_toml)
    assert parsed.get("web_search") == CodexWebSearchMode.LIVE.value
    assert set(parsed.get("mcp_servers", {})) == set(_HARNESS_SERVERS)


@pytest.mark.service
def test_web_search_invokes_and_completes_under_readonly_sandbox(
    live_turn: _TurnObservation,
) -> None:
    """A real search runs and completes with the headless posture in force.

    The approval half is proven by outcome rather than by absence alone: the
    production protocol client answers every server-initiated request with a
    JSON-RPC "method not found", so a tool that needed an approval round-trip
    could not have completed. A completed search under
    ``approval_policy = never`` + ``sandbox = read-only`` is therefore the
    undocumented axis settled - the sandbox does not withhold the server-side
    tool, and the never policy does not park it on a prompt nobody answers.
    """
    assert CodexChatModel.model_fields["approval_policy"].default == "never"
    assert CodexChatModel.model_fields["sandbox"].default == "read-only"

    searches = live_turn.web_searches()
    assert searches, (
        "the live-mode turn completed without a single webSearch item; the "
        f"posture did not surface the tool (status={live_turn.status!r})"
    )
    reached = [url for item in searches for url in _urls_of(item)]
    assert any(_host_matches(url) for url in reached), (
        f"no webSearch item reached {_SOURCE_HOST}; URLs seen: {reached!r}"
    )
    assert live_turn.status == "completed", (
        f"the retrieval turn ended {live_turn.status!r}, not completed"
    )
    assert not live_turn.approval_frames(), (
        "the never-approval policy still produced approval traffic: "
        f"{live_turn.approval_frames()!r}"
    )


@pytest.mark.service
def test_retrieval_returns_a_current_fact_the_model_cannot_recall(
    live_turn: _TurnObservation,
) -> None:
    """The answer carries the version the index is publishing right now.

    This is the assertion that separates a retrieval from a recollection, and it
    is sharper than that: it also separates a LIVE retrieval from an indexed one.
    Driven with the posture set to cached, this same turn answered the previous
    day's release - a genuine retrieval from a provider-maintained index, and
    still the wrong answer - so a value only the live index can supply is what the
    served posture has to produce.

    The frames cannot make this claim: they carry the URL the tool opened and the
    result metadata, never the page body, so only the content of the answer shows
    that retrieved material reached the model.
    """
    assert live_turn.current_versions, "the index served no version to compare against"
    assert any(version in live_turn.text for version in live_turn.current_versions), (
        "the turn reported none of the versions the index was publishing "
        f"{sorted(live_turn.current_versions)}; answer was: "
        f"{live_turn.text.strip()[:400]!r}"
    )


@pytest.mark.service
def test_disabled_posture_performs_no_search_at_all(
    disabled_turn: _TurnObservation,
) -> None:
    """The control: the identical prompt under ``disabled`` reaches nothing.

    Without this, a search observed under the live posture would prove only that
    Codex searches - not that the configuration is what let it. The turn must
    still COMPLETE: the posture withholds the tool, it does not break the lane.
    """
    parsed = tomllib.loads(disabled_turn.config_toml)
    assert parsed.get("web_search") == CodexWebSearchMode.DISABLED.value
    assert not disabled_turn.web_searches(), (
        "the disabled posture still performed a web search: "
        f"{disabled_turn.web_searches()!r}"
    )
    assert disabled_turn.status == "completed", (
        f"the control turn ended {disabled_turn.status!r}, not completed"
    )


@pytest.mark.service
def test_proven_lane_resolves_the_served_live_posture(
    external_prerequisite: ExternalPrerequisiteRule, tmp_path: Path
) -> None:
    """The production gate, not a rehearsal of it: the real model emits live.

    Reads the verdict through the same call chain a spawn takes - lane admission,
    posture resolution, the chat model's own config-home build - so the entry
    recorded in the declaration is what puts ``live`` into the document a real
    run consumes. Without the entry every one of these yields ``disabled``, which
    is exactly what this asserts is no longer the case for this lane.
    """
    _require_codex(external_prerequisite)
    assert is_web_lane_proven(Provider.CODEX) is True
    assert (
        resolve_codex_web_search_mode(web_proven=is_web_lane_proven(Provider.CODEX))
        is SERVED_WEB_SEARCH_MODE
    )

    model = ProviderFactory().create(
        Provider.CODEX, model=Model.LOW, workspace_root=tmp_path
    )
    assert isinstance(model, CodexChatModel)
    composed = model.with_harness_mcp_servers(list(_HARNESS_SERVERS))
    home = composed._build_codex_config_home()
    assert home is not None
    try:
        parsed = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    finally:
        cleanup_codex_config_home(home)
    assert parsed.get("web_search") == SERVED_WEB_SEARCH_MODE.value


@pytest.mark.service
@pytest.mark.asyncio
async def test_production_research_chain_lands_a_typed_web_locator(
    external_prerequisite: ExternalPrerequisiteRule,
    published_version: str,
    tmp_path: Path,
) -> None:
    """The whole production chain: a real retrieval becomes checkpointed evidence.

    The real provider factory builds the model, the real research producer runs
    the turn and promotes the sources it cites, and the real researcher node
    validates the result against the finding contract before returning the state
    update the reducer appends. What lands is a typed web locator carrying the
    retrieval's own URL - the form the citation channel admits - rather than a URL
    loose in prose.

    This is the leg that depends on the lane's recorded proof: the model resolves
    its posture through lane admission, so an unproven lane runs this turn with
    search disabled and reaches nothing to cite.
    """
    _require_codex(external_prerequisite)
    model = ProviderFactory().create(
        Provider.CODEX, model=Model.LOW, workspace_root=tmp_path
    )
    producer = _make_research_producer(
        model,
        "You are a researcher. Cite every external source by its full URL.",
        workspace_root=tmp_path,
        harness_mcp_servers=list(_HARNESS_SERVERS),
        autonomous=True,
    )
    node = create_researcher_node(
        {
            "thread_id": "codex-web-grounding",
            "topic": "current published version of the package index entry",
            "instructions": _PROMPT,
        },
        producer,
    )

    state: TeamState = {
        "active_agent": "researcher",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content=_PROMPT)],
        "next": "",
        "thread_id": "codex-web-grounding",
        "active_feature": "codex-web-grounding",
        "workspace_root": str(tmp_path),
        "token_usage": {},
    }
    update = await node(state)

    findings = update["research_findings"]
    assert len(findings) == 1
    finding = json_object(findings[0], at="research finding")
    web_locators: list[JsonObject] = []
    for raw_locator in json_list(
        finding.get("locators"), at="research finding locators"
    ):
        locator = json_object(raw_locator, at="research finding locator")
        if locator.get("kind") == WEB_LOCATOR_KIND:
            web_locators.append(locator)
    assert web_locators, (
        "the research chain produced no typed web locator; the turn cited no "
        f"retrievable source. Claim was: {finding.get('claim')!s:.400}"
    )
    locator_urls = [
        json_text(locator.get("url"), at="research finding locator.url")
        for locator in web_locators
    ]
    assert any(_host_matches(url) for url in locator_urls), (
        f"no web locator names {_SOURCE_HOST}: {locator_urls!r}"
    )
    for locator, locator_url in zip(web_locators, locator_urls, strict=True):
        assert locator["retrieved_at"]
        assert urlsplit(locator_url).scheme in {"http", "https"}
