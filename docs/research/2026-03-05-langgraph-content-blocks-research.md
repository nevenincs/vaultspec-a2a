# LangGraph Standard Content Blocks Research

## Source
LangChain Official Documentation (Message Content Blocks, LangSmith Trace Logs)

## Relevance
**Score: 10/10**
Crucial for maintaining architectural integrity in the A2A orchestrator. We must avoid ad-hoc `xml` string tags for reasoning/multimodality and instead rely strictly on standard typed dictionaries supported natively by LangGraph and LangSmith.

## Supported Content Types
LangChain provides a standard representation for message content that works across providers. The `content` attribute of `AIMessage` (and others) can be a string, but for rich or extended capabilities, it should be a list of typed dictionaries. 

The officially supported types are:

1. **`text`**: Standard text output type.
   - `type`: "text"
   - `text`: Text string.
   - `annotations`: (Optional) List of annotations.
   - `extras`: (Optional) Additional provider-specific data.

2. **`reasoning`**: Model reasoning or internal "thinking" steps (replacing ad-hoc `<thought>` tags).
   - `type`: "reasoning"
   - `reasoning`: The inner thoughts/reasoning string.
   - `extras`: (Optional) Provider data (e.g., signature).

3. **`image`**: Multimodal image data.
   - `type`: "image"
   - `url`: URL to the image, OR
   - `base64`: Base64 encoded string with `mime_type` (e.g., "image/png").
   - `id`: (Optional) External storage ID.

4. **`file`**: Document/file data (e.g., PDFs).
   - `type`: "file"
   - `url` or `base64`.

5. **`audio`**: Audio data.
   - `type`: "audio"
   - `url` or `base64`.

6. **`video`**: Video data.
   - `type`: "video"
   - `url` or `base64`.

7. **`tool_call`**: Tool invocation block.
   - Note: Usually LangChain moves these to `AIMessage.tool_calls`, but within `content_blocks` Anthropic-style models may emit these inline.

8. **`server_tool_call` / `server_tool_result`**: Explicit MCP (Model Context Protocol) specific blocks for multi-server MCP setups.

## Implementation Strategy
To ensure Vaultspec's orchestration pipeline is fully robust, our `MockChatModel` and corresponding YAML tapes must exercise a diverse array of these types. 

We will refactor our high-priority tapes (like `mock-coder-success` and `mock-planner`) to include:
- `reasoning` blocks for planning.
- `text` blocks for standard conversational emission.
- `image` / `audio` / `file` blocks to simulate multimodal tool outputs or user prompts.
- Inline `tool_call` blocks if testing provider-specific message passing.
