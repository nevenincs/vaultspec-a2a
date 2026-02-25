# Phase 1 Research: Gemini Agent Support and Specificities

**Date**: 2026-02-25
**Provider**: Gemini
**Status**: Research Complete

---

## 1. Authentication Process
**Local CLI vs. Direct Online APIs**
The Gemini CLI operates as a hybrid system. It utilizes Google's remote Gemini APIs (AI Studio or Vertex AI) for model reasoning and text generation, but relies on local execution for tool use (e.g., file system access, terminal commands).

**Authentication Methods:**
- **Interactive Local CLI**: For local execution, the recommended method is "Login with Google", which uses a web browser to authenticate personal or workspace accounts via OAuth.
- **Direct Online APIs (Headless/Automated)**:
  - **API Key**: Users can set the `GEMINI_API_KEY` environment variable from Google AI Studio. This is the preferred method for headless, automated environments, or A2A orchestration.
  - **Vertex AI**: Supports Google Cloud Application Default Credentials (ADC) via the `gcloud` CLI, Service Account JSON keys (`GOOGLE_APPLICATION_CREDENTIALS`), or Google Cloud API keys.
  - **Automatic Cloud Auth**: When running within Google Cloud Shell or Compute Engine, the CLI can automatically authenticate using environment metadata.

**Emerging Consensus:** For multi-agent orchestration via A2A or MCP, the emerging consensus is to rely on non-interactive, token-based authentication (like `GEMINI_API_KEY` or Vertex ADC). Interactive browser-based logins block automated agent workflows, making environment-variable-based direct API access the standard.

## 2. Agent Client Protocol (ACP) Support
- **Native Integration**: Gemini CLI natively supports ACP. Recent updates (e.g., v0.28.0) have solidified "ACP mode," including features like session resume and improved environment loading.
- **Capabilities**: Through ACP, Gemini CLI can maintain persistent sessions, stream agent thoughts, manage terminal processes, and handle user permission flows. This makes it an ideal candidate to act as either an ACP host or a controlled agent within an ACP-compliant IDE (like Toad or Zed).

## 3. Agent-to-Agent (A2A) Support
- **Protocol Adoption**: Gemini CLI has adopted the A2A protocol for delegating tasks to remote agents. It treats external specialized agents as "remote subagents."
- **Configuration & Discovery**: A2A support is currently an experimental feature (enabled via `settings.json`: `"experimental": { "enableAgents": true }`). Remote agents are discovered and defined using Markdown files containing YAML frontmatter that specifies the `agent_card_url`.
- **Framework Integration**: Gemini orchestrates its team by exposing both local and remote sub-agents as tools to the main agent. It delegates tasks based on the Agent Cards. This aligns perfectly with the A2A standard of using Agent Cards for capability discovery.

## 4. Technical Requirements for Integration
To successfully integrate Gemini into the proposed coding-teams framework:
- **Auth**: The orchestrator must be capable of injecting `GEMINI_API_KEY` or Vertex AI credentials into the Gemini agent's environment without requiring an interactive browser session.
- **Execution Mode**: The agent should be launched in "Headless Mode" (or "ACP mode") to avoid TUI/interactive prompts blocking the A2A or MCP message flows.
- **Autonomy**: Utilize "YOLO mode" (You Only Look Once) where appropriate, or rely on ACP's permission request mechanisms for human-in-the-loop authorization on sensitive operations (like `write_file`).
- **Tool Access**: Gemini CLI supports MCP servers natively, meaning it can both consume external tools via MCP and potentially expose its capabilities to the A2A orchestrator.

## 5. Pricing & API Usage
**Subscriptions vs. API Billing**
The **Gemini Advanced** consumer subscription (part of Google One AI Premium) and the **Gemini API** are completely separate billing systems.
- **Interactive/Subscription Model**: The $20/month Gemini Advanced subscription gives users premium access to the chat UI and Google apps integrations. However, **this subscription does not grant API access or API keys**.
- **API Model**: Programmatic access (required for agent orchestration) uses the **Gemini API** via Google AI Studio. This is a separate, usage-based (pay-as-you-go) billing system.
- **Free Tier**: The Gemini API offers a robust free tier with rate limits, which developers can use without cost. However, the paid tier ensures data privacy (not used for training).
- **Summary**: To run the Gemini CLI as an automated agent, developers must generate an API key in Google AI Studio and rely on either the free tier or the pay-as-you-go plan. A monthly consumer subscription does not cover API key usage.
