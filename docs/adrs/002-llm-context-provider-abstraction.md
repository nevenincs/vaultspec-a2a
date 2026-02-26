---
adr_id: 002
title: LLM Context & Provider Abstraction
date: 2026-02-25
status: Proposed
related:
  - docs/distilled/2026-25-02-agents-distilled.md
  - docs/distilled/2026-25-02-agents-gaps-research.md
  - docs/distilled/2026-25-02-architecture-distilled.md
  - docs/distilled/2026-25-02-architecture-gaps-research.md
  - docs/agents/2026-25-02-claude-agent-support.md
  - docs/agents/2026-25-02-gemini-agent-support.md
  - docs/agents/2026-25-02-codex-agent-support.md
  - docs/agents/2026-25-02-glm5-agent-support.md
---

# ADR-002: LLM Context & Provider Abstraction

**Date:** 2026-02-25  
**Status:** Proposed

## 1. Context & Problem Statement

The orchestrator must manage the cognitive state and authentication of a
multi-agent team (Claude, Gemini, GLM-5, etc.). This presents two
critical challenges:

* **Cost & Authentication:** Using standard developer API keys for
  agentic coding loops incurs massive, unpredictable costs. The
  orchestrator must wrap provider CLIs to inherit the user's flat-rate
  consumer subscriptions (e.g., Claude Pro, Gemini Advanced). If cached
  session tokens expire mid-task, the orchestrator will crash due to
  unhandled `401 Unauthorized` errors.
* **Context Window Exhaustion:** Agents discussing a project and reading
  files will rapidly exceed maximum context windows (e.g., 200k tokens).
  If a Planner agent attempts to pass its entire thought history to a
  Coder agent, the API will reject the payload, instantly halting the
  team.

## 2. The Decision

### Provider Abstraction & Authentication: Dual Architecture

* **ACP-LangChain Wrapper Architecture (`AcpChatModel`):** The
  orchestrator will **not** use standard REST LangChain SDKs (e.g.,
  `ChatAnthropic`) to communicate with flat-rate consumer models
  (Claude, Gemini) because those SDKs strictly expect developer
  `x-api-key` headers and reject consumer OAuth tokens with `401
  Unauthorized`. Instead, we build `AcpChatModel` — a custom
  `BaseChatModel` in `lib/providers/acp_chat_model.py` — that spawns
  the provider's CLI as a managed subprocess and communicates via
  JSON-RPC over `stdio`.
  * **Zero PTY / Zero Batch:** Subprocesses are invoked without a PTY
    and never via `cmd.exe /c`. This is critical for pipe integrity on
    Windows.
  * **For Claude:** `AcpChatModel` resolves the `@zed-industries` npm
    package's raw deployment path (`dist/index.js`) via filesystem
*   **ACP-LangChain Wrapper Architecture (`AcpChatModel`):** The
    orchestrator will **not** use standard REST LangChain SDKs (e.g.,
    `ChatAnthropic`) to communicate with flat-rate consumer models
    (Claude, Gemini) because those SDKs strictly expect developer
    `x-api-key` headers and reject consumer OAuth tokens with `401
    Unauthorized`. Instead, we build `AcpChatModel` — a custom
    `BaseChatModel` in `lib/providers/acp_chat_model.py` — that spawns
    the provider's CLI as a managed subprocess and communicates via
    JSON-RPC over `stdio`.
    *   **Zero PTY / Zero Batch:** Subprocesses are invoked without a PTY
        and never via `cmd.exe /c`. This is critical for pipe integrity on
        Windows.
    *   **For Claude:** `AcpChatModel` resolves the `@zed-industries` npm
        package's raw deployment path (`dist/index.js`) via filesystem
        resolution and invokes it under `node.exe` directly.
        `CLAUDE_CODE_OAUTH_TOKEN=<token>` is injected into the subprocess
        `env` dict. Token acquisition: user runs `claude setup-token` once,
        generating a static headless token with a ~1-year lifecycle. This
        has been **validated** — injecting the token immediately bypasses
        the CLI login prompt.
    *   **For Gemini:** The Gemini CLI installs as a `.CMD` npm shim
        (verified: `C:\Users\...\npm\gemini.CMD`), **not** a native `.exe`.
        However, `create_subprocess_shell("gemini --experimental-acp")` is
        safe because the OS shell resolves `.CMD` shims natively — no
        `shutil.which` resolution or `cmd.exe /c` wrapping is needed. Zero
        credential injection: Gemini CLI manages its own OAuth from
        `~/.gemini/oauth_creds.json`. This was **validated** via probe on
        2026-02-26 — initialize, session/new, session/prompt, and
        end_turn all succeeded with no injected credentials.
    *   **Protocol Parity:** Both Claude and Gemini speak identical ACP
        JSON-RPC (verified by Toad's `geminicli.com.toml` which uses the
        same `Agent` class as Claude — only the command string differs).
*   **Direct API Architecture (GLM-5 only):** Zhipu's GLM-5 remains the
    sole exception. It lacks a consumer CLI, so the orchestrator
    interacts directly with its REST API via `langchain_openai` with
    `base_url` override and a traditional `x-api-key` header.

### Context Management

*   **State Checkpointing (LangGraph Pattern):** We will explicitly
    decouple the *Conversation History* from the *Architectural State*.
    The Orchestrator will maintain a strict `TypedDict` representing the
    compiled state of the project (e.g., `current_plan`, `files_to_edit`,
    `approved_code`).
*   **Clean Handoffs:** When transferring control from one agent to
    another (e.g., Planner → Coder), the Orchestrator will initialize the
    receiving agent with *only* the explicitly compiled `State` object
    via the A2A `ContextId`. The transmitting agent's internal reasoning
    loops (e.g., a 50-turn deliberation) are intentionally dropped.

## 3. Rationale

*   **Cost & Stability:** Using 1-year headless OAuth tokens driving
    official CLIs completely eliminates the need for the orchestrator to
    build complex polling logic to catch `401` refresh race conditions.
    Crucially, the CLI wrapper architecture entirely bypasses
    pay-as-you-go developer billing APIs, absorbing agentic coding loops
    into the user's flat-rate $20/month subscription.
*   **Amnesia Prevention:** "Sliding Window" truncation (dropping the
    oldest 10 messages) causes fatal "amnesia," where the Coder forgets
    the core requirements defined by the Planner at the start of the
    session. Checkpointing guarantees the core objective is preserved
    while resetting token usage to ~1k per handoff.
*   **GLM-5 Simplicity:** Recognizing that GLM-5 natively supports
    standard OpenAI function calling schemas eliminates a massive amount
    of unnecessary mapping code in the provider adapter layer, making it
    the perfect candidate for our direct `x-api-key` integration.

## 4. Rejected Alternatives

*   **Interactive `/login` tokens:** Rejected. The OAuth tokens generated
    by standard interactive browser logins are aggressively rotated and
    typically expire within 8–12 hours. They are entirely unsuitable for
    a headless orchestrator service.
*   **LangChain SDKs for Frontier Models:** Rejected. Injecting an OAuth
    token into `ChatAnthropic(api_key=...)` results in `401
    Unauthorized` errors because the LangChain adapter strictly hits the
    developer API endpoint (expecting `x-api-key`), not the consumer
    endpoint the CLI is wired for.
*   **cmd.exe / PTY subprocess invocation:** Rejected. Using
    `cmd.exe /c node claude-agent-acp` or a PTY to launch CLIs destroys
    pipe framing on Windows. `node.exe` must be resolved and invoked
    directly via filesystem path resolution.
*   **`shutil.which` for Claude:** Rejected. Claude does not deploy as
    `claude.exe` — it deploys as a Node.js package.
    `shutil.which("claude")` resolves a `.CMD` shim, which is banned.
    The raw `dist/index.js` path must be resolved from the npm package
    location.
*   **`shutil.which` for Gemini:** Not needed.
    `create_subprocess_shell` handles the `.CMD` shim natively. Using
    `shutil.which("gemini")` to get the path and then
    `create_subprocess_exec` would break — it would try to execute the
    `.CMD` file directly without a shell interpreter.
*   **Sliding-Window Truncation:** Rejected. As noted, it corrupts the
    structural integrity of long-horizon tasks.
*   **Sharing Full Chat History:** Rejected. It guarantees an
    out-of-memory/token-exhaustion failure on complex tasks.

## 5. Implementation Constraints & Pitfalls

* **Credential Leakage:** Tokens are passed via the `env` dict in
  `subprocess.Popen` (never via command-line arguments, which appear in
  process listings). `CLAUDE_CODE_OAUTH_TOKEN` and Gemini credentials
  must **never** be logged to `stdout`/`stderr`, captured in LangSmith
  traces, or forwarded to the frontend UI.
* **Node.js Path Resolution Brittleness:** The `@zed-industries` npm
  package installation path for `dist/index.js` must be resolved at
  runtime (e.g., via `node --print
  "require.resolve('@zed-industries/claude-agent-acp')"` or filesystem
  traversal from the known npm prefix). Hardcoding absolute paths will
  break across machines.
* **Serialization Integrity:** The `TeamState` (`TypedDict`) must remain
  strictly serializable to JSON so it can be losslessly encoded and
  decoded as it passes through the A2A protocol payloads.

## 6. Negative Consequences

* **Provider Volatility:** We are relying on consumer-facing OAuth token
  flows for Claude and Gemini. The providers could break, rotate, or
  deprecate these headless setup flows at their discretion, requiring
  immediate updates to the orchestrator's authentication layer.
* **Loss of Subtle Context:** By aggressively dropping an agent's
  internal reasoning loops during handoff, the receiving agent may miss
  subtle, undocumented rationale for *why* a certain decision was made,
  unless the transmitting agent explicitly writes it into the
  `TeamState`.

## 7. References

### 7.1 Local Research & Distilled Docs

* [Agents Domain - Distilled](../distilled/2026-25-02-agents-distilled.md)
* [Agents Gaps Research](../distilled/2026-25-02-agents-gaps-research.md)
* [Architecture Domain - Distilled](../distilled/2026-25-02-architecture-distilled.md)
* [Architecture Gaps Research](../distilled/2026-25-02-architecture-gaps-research.md)
* [Claude Agent Support](../agents/2026-25-02-claude-agent-support.md)
* [Gemini Agent Support](../agents/2026-25-02-gemini-agent-support.md)
* [GLM-5 Agent Support](../agents/2026-25-02-glm5-agent-support.md)

### 7.2 Codebase Modules & Patterns

* **Authentication/Environment Injection:** `os.environ` (Python
  standard library) and `subprocess.Popen` (standard library).
* **GLM-5 Integration:** `openai` Python package
  (`openai.OpenAI(base_url=...)`) for OpenAI-compatible API
  interaction.
* **Context Management:** `typing.TypedDict` (Python standard library)
  for defining structured state objects.
* **State Checkpointing:** Patterns observed in
  `knowledge/repositories/langgraph/` for state management within
  agentic workflows.
* **A2A Context Handoff:** `a2a.types.ContextId`
  (`knowledge/repositories/a2a-python/src/a2a/types.py`) for
  maintaining conversation threads between agents.

### 7.3 Online Reference Implementation

* **Claude `setup-token`:** [Claude Code CLI
  Documentation](https://code.claude.com/docs/) (specific section on
  headless authentication).
* **LangGraph Checkpointers:** [LangChain/LangGraph
  Documentation](https://python.langchain.com/docs/modules/agents/how_to/memory_types/)
  (section on "Memory and Checkpointing" for agent state).
* **OpenAI Compatible APIs:** [Zhipu AI GLM-5 API
  Documentation](https://open.bigmodel.cn/dev/api#glm-5) (referenced
  for tool-calling format and `base_url` override).
