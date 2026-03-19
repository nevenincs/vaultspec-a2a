---
name: 'MCP Tool Description Best Practices'
date: 2026-03-02
type: research
summary: 'Best practices for writing MCP tool names, descriptions, and parameter annotations to maximize LLM discoverability and correct invocation.'
maturity: 80
feature: mcp-tool-descriptions
---

# Research: MCP Tool Description Best Practices for LLM Discoverability

**Date**: 2026-03-02
**Status**: Complete
**Requested by**: team-lead
**Purpose**: Inform audit and rewrite of `src/vaultspec_a2a/protocols/mcp/server.py` tool docstrings

---

## 1. How LLMs Consume Tool Descriptions

When a client (Claude, GPT, Gemini) receives MCP tools via `tools/list`, the
tool definitions are injected into the LLM's context as part of the system
prompt. The LLM uses three fields to decide when and how to call a tool:

1. **Tool name** — used for routing/selection (the "what")
2. **Tool description** — used for understanding purpose, caveats, and when
   to use it (the "why" and "when")
3. **Parameter descriptions** — used for constructing correct input (the "how")

All three fields consume tokens on every API call. Tool definitions are part
of the context window, not free metadata. This creates a tension between
thoroughness and token efficiency.

---

## 2. Tool Naming Conventions

### 2.1 MCP SDK Convention

The MCP Python SDK uses the Python function name as the tool name by default
with `@mcp.tool()`. The SDK examples use `snake_case`:

```python
@mcp.tool()
def get_weather(city: str) -> str: ...

@mcp.tool()
def sum(a: int, b: int) -> int: ...
```

### 2.2 Cross-Platform Patterns

| Source             | Convention        | Examples                           |
| ------------------ | ----------------- | ---------------------------------- |
| MCP SDK            | `snake_case`      | `get_weather`, `long_running_task` |
| OpenAI             | `snake_case`      | `get_weather`, `get_location`      |
| Anthropic          | `snake_case`      | `get_weather`, `get_time`          |
| GitHub MCP servers | `slash_namespace` | `github_create_issue`              |

### 2.3 Best Practices for Names

1. **Use `snake_case`** — universally understood by all LLM providers.
2. **Use verb-noun pattern** — `start_thread`, `list_threads`, `cancel_thread`.
   Verb-first makes the action immediately clear.
3. **Be specific, not generic** — `list_team_presets` is better than `list`.
   When many tools are available, specificity prevents selection ambiguity.
4. **Namespace if needed** — For servers with many tools, prefix with domain:
   `thread_list`, `thread_cancel`, `team_list`. But avoid over-nesting.
5. **Keep names short** — Names consume tokens on every call. 2-3 words is
   ideal. Avoid names longer than 40 characters.

---

## 3. Tool Description Best Practices

### 3.1 Anthropic's Guidance (Authoritative for Claude)

Anthropic's official documentation states:

> **"Provide extremely detailed descriptions. This is by far the most important
> factor in tool performance."**

Specific guidance:

- **Aim for at least 3-4 sentences per tool description**, more for complex tools.
- Explain every detail about the tool including **important caveats or limitations**.
- State **what information the tool does NOT return** if the tool name is unclear.
- **Prioritize descriptions over examples** — while examples can help, a clear
  and comprehensive explanation of purpose and parameters matters more.
- Only add examples **after** you have fully fleshed out the description.
- **Document return formats clearly** since the LLM writes code to parse outputs.

### 3.2 OpenAI's Guidance

OpenAI recommends:

- Be **concise but descriptive** — tool definitions become part of context on
  every call, affecting cost and latency.
- Use **strict mode** (`strict: true`) to ensure function calls reliably
  adhere to the schema.
- **Auto-generate JSON schemas** from type definitions where possible.

### 3.3 MCP Spec Guidance

The MCP specification and documentation recommend:

- Provide **clear, descriptive names and descriptions**.
- Use **detailed JSON Schema definitions** for parameters.
- Include **examples in tool descriptions** to demonstrate usage.
- Document **expected return value structures**.

### 3.4 Synthesized Description Structure

Based on all three sources, a well-crafted tool description should follow
this structure:

```
[1-sentence purpose statement — what this tool does]

[1-2 sentences on when to use it and when NOT to use it]

[Caveats, limitations, side effects — what the user should know]

[Return format — what the output looks like and what fields mean]
```

**Example — good description:**

```python
@mcp.tool()
async def start_thread(initial_message: str, team_preset: str | None = None) -> str:
    """Start a new Vaultspec multi-agent coding workflow.

    Use this tool when the user wants to delegate a coding task to a team of
    AI agents. The workflow runs asynchronously — this tool returns immediately
    with a thread ID. Use 'get_thread_status' to monitor progress.

    The thread runs in autonomous mode by default (agents auto-approve all
    permission requests). Set autonomous=False if the user wants to review
    agent actions before they execute.

    Returns: A plain-text confirmation containing the thread ID, team preset
    name, and URLs for monitoring the thread via REST and WebSocket.
    """
```

**Example — bad description (too terse):**

```python
@mcp.tool()
async def start_thread(initial_message: str) -> str:
    """Start a new thread."""
```

### 3.5 Description Length Guidance

| Provider  | Minimum       | Recommended          | Maximum                                 |
| --------- | ------------- | -------------------- | --------------------------------------- |
| Anthropic | 3-4 sentences | 4-6 sentences        | No hard limit, but token cost increases |
| OpenAI    | 1 sentence    | 2-3 sentences        | "Concise but descriptive"               |
| MCP Spec  | Not specified | "Clear, descriptive" | Not specified                           |

**Recommendation for vaultspec**: Aim for **4-6 sentences** per tool. Our MCP
server has fewer than 10 tools, so the token overhead is minimal. Thorough
descriptions dramatically improve selection accuracy.

---

## 4. Parameter Description Best Practices

### 4.1 MCP SDK Pattern

In FastMCP, parameter descriptions come from Python type annotations and
docstrings. The SDK auto-generates JSON Schema from function signatures:

```python
@mcp.tool()
def get_weather(
    city: str,           # becomes {"type": "string"} in JSON Schema
    unit: str = "celsius" # default value makes it optional
) -> str:
    """Get weather for a city."""
```

For richer parameter descriptions, use Pydantic `Field`:

```python
from pydantic import Field

class WeatherData(BaseModel):
    temperature: float = Field(description="Temperature in Celsius")
    humidity: float = Field(description="Humidity percentage")
```

### 4.2 Cross-Provider Parameter Patterns

| Practice                | Anthropic                       | OpenAI                  | MCP                 |
| ----------------------- | ------------------------------- | ----------------------- | ------------------- |
| Include format examples | Yes: `"e.g. San Francisco, CA"` | Yes: same pattern       | Yes                 |
| Document enum values    | Yes: in description             | Yes: `"enum"` field     | Yes: JSON Schema    |
| State constraints       | Yes: in description             | Yes: schema constraints | Yes: JSON Schema    |
| Document defaults       | Yes: in description             | Yes: schema `default`   | Yes: Python default |

### 4.3 Synthesized Parameter Description Rules

1. **Always include a format example** for string parameters:

   ```
   "The thread ID returned by start_thread, e.g. '550e8400-e29b-41d4-a716-446655440000'"
   ```

2. **State valid values explicitly** for constrained parameters:

   ```
   "Team preset ID. Valid values: 'vaultspec-adaptive-coder', 'vaultspec-solo-coder', etc.
    Use list_team_presets to discover available presets."
   ```

3. **Document what happens with None/default** for optional parameters:

   ```
   "Workspace root path. If omitted, context injection is disabled and the
    thread runs without project-specific files."
   ```

4. **Cross-reference related tools** in parameter descriptions:

   ```
   "The thread_id returned by start_thread. Use list_threads to find
    existing thread IDs."
   ```

5. **State constraints in natural language** (LLMs parse this better than
   raw JSON Schema):

   ```
   "Maximum 32,000 characters. Longer messages are rejected."
   ```

---

## 5. Return Value Documentation

### 5.1 Anthropic's Guidance

> **"Document return formats clearly"** since Claude writes code to parse outputs.

Recommended pattern:

```
Returns: List of thread objects, each containing:
  - thread_id (str): Unique thread identifier
  - status (str): One of 'running', 'completed', 'failed', 'cancelled'
  - title (str): Thread title (first 80 chars of initial message)
  - created_at (str): ISO 8601 timestamp
```

### 5.2 Structured vs. Plain-Text Returns

The MCP SDK supports structured outputs via Pydantic models, TypedDict, or
plain dict returns. For IDE integration:

- **Structured returns** (Pydantic/TypedDict) are preferred when the LLM
  needs to extract specific fields from the response for further processing.
- **Plain-text returns** are acceptable for terminal display or when the
  response is the final output shown to the user.

**Recommendation for vaultspec**: Our current tools return plain text strings.
This is acceptable for the current use case (IDE display). If we add tools
where the LLM needs to chain outputs (e.g., get thread ID from list, then
pass to cancel), structured returns would improve reliability.

---

## 6. Common Anti-Patterns

### 6.1 Descriptions That Cause Misselection

| Anti-Pattern              | Problem                         | Fix                                     |
| ------------------------- | ------------------------------- | --------------------------------------- |
| Identical first sentences | LLM can't distinguish tools     | Differentiate in first 10 words         |
| Jargon-only descriptions  | LLM may not know domain terms   | Use plain language first, jargon second |
| Missing negative guidance | LLM uses tool when it shouldn't | Add "Do NOT use this tool for..."       |
| No return format          | LLM guesses output shape        | Document return structure               |
| Overly long descriptions  | Token waste, attention dilution | Front-load key info, trim filler        |

### 6.2 Parameter Descriptions That Cause Hallucination

| Anti-Pattern        | Problem                       | Fix                                       |
| ------------------- | ----------------------------- | ----------------------------------------- |
| No format example   | LLM invents format            | Add `"e.g. ..."`                          |
| Ambiguous type      | LLM sends wrong type          | Use strict JSON Schema types              |
| Missing constraints | LLM sends out-of-range values | State limits in description               |
| No cross-reference  | LLM guesses parameter values  | Reference tool that provides valid values |

---

## 7. Audit Checklist for Vaultspec MCP Tools

Apply this checklist when reviewing each tool in `src/vaultspec_a2a/protocols/mcp/server.py`:

- [ ] **Name**: snake_case, verb-noun, specific, under 40 chars
- [ ] **Description line 1**: Clear purpose statement (what it does)
- [ ] **Description line 2-3**: When to use / when NOT to use
- [ ] **Description line 4+**: Caveats, side effects, limitations
- [ ] **Return format**: Documented in description
- [ ] **Each parameter**: Has description with format example
- [ ] **Optional params**: Default behavior documented
- [ ] **Cross-references**: Related tools mentioned where helpful
- [ ] **Negative guidance**: States what the tool does NOT do
- [ ] **Length**: 4-6 sentences minimum for description

---

## 8. Application to Current Vaultspec MCP Tools

### 8.1 `start_thread` — Current State

```python
"""Start a new Vaultspec agent team workflow. Returns immediately with thread_id."""
```

**Issues**:

- Only 1 sentence (should be 4-6)
- No guidance on when to use vs. send_message
- No return format documentation
- Parameters lack format examples

### 8.2 `get_thread_status` — Current State

```python
"""Query the current status and message count of a thread."""
```

**Issues**:

- Only 1 sentence
- No return format documentation
- No guidance on polling frequency
- thread_id parameter has no format example

### 8.3 `send_message` — Current State

```python
"""Send a follow-up message into an existing thread (async, returns 202)."""
```

**Issues**:

- Only 1 sentence
- Leaks HTTP detail ("202") irrelevant to MCP consumer
- No guidance on when to use vs. start_thread
- No return format documentation

---

## 9. Sources

- [Anthropic Tool Use Documentation](https://platform.claude.com/docs/en/docs/build-with-claude/tool-use) — authoritative guidance on Claude tool descriptions
- [OpenAI Function Calling Guide](https://platform.openai.com/docs/guides/function-calling) — OpenAI best practices
- [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25) — protocol-level tool definition
- [MCP Tools Concepts](https://modelcontextprotocol.info/docs/concepts/tools/) — MCP tool design guidance
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — FastMCP reference implementation
- [OpenAI Community: Tool Use Best Practices](https://community.openai.com/t/prompting-best-practices-for-tool-use-function-calling/1123036) — community discussion
- [Anthropic Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use) — scaling tool orchestration
