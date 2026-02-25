---
name: "A2A Protocol Extensions"
date: 2026-25-02
type: reference
summary: "Extension system covering scope, declaration in Agent Cards, activation via headers, versioning, and Python implementation examples."
maturity: 75
---

# A2A Protocol Extensions Reference

The Agent2Agent (A2A) protocol provides a strong foundation for inter-agent
communication. However, specific domains or advanced use cases often require
additional structure, custom data, or new interaction patterns beyond the
generic methods. Extensions are A2A's powerful mechanism for layering new
capabilities onto the base protocol.

Extensions allow for extending the A2A protocol with new data, requirements, RPC
methods, and state machines. Agents declare their support for specific
extensions in their Agent Card, and clients can then opt in to the behavior
offered by an extension as part of requests they make to the agent. Extensions
are identified by a URI and defined by their own specification. Anyone is able
to define, publish, and implement an extension.

The flexibility of extensions allows for customizing A2A without fragmenting the
core standard, fostering innovation and domain-specific optimizations.

## SCOPE OF EXTENSIONS

The exact set of possible ways to use extensions is intentionally broad,
facilitating the ability to expand A2A beyond known use cases. However, some
foreseeable applications include:

* **Data-only Extensions:** Exposing new, structured information in the Agent
  Card that doesn't impact the request-response flow. For example, an extension
  could add structured data about an agent's GDPR compliance.
* **Profile Extensions:** Overlaying additional structure and state change
  requirements on the core request-response messages. This type effectively acts
  as a profile on the core A2A protocol, narrowing the space of allowed values
  (for example, requiring all messages to use DataParts adhering to a specific
  schema). This can also include augmenting existing states in the task state
  machine by using metadata. For example, an extension could define a
  'generating-image' substate when `TaskStatus.state` is 'working' and
  `TaskStatus.message.metadata["generating-image"]` is true.
* **Method Extensions (Extended Skills):** Adding entirely new RPC methods
  beyond the core set defined by the protocol. An Extended Skill refers to a
  capability or function an agent gains or exposes specifically through the
  implementation of an extension that defines new RPC methods. For example, a
  `task-history` extension might add a `tasks/search` RPC method to retrieve a
  list of previous tasks, effectively providing the agent with a new, extended
  skill.
* **State Machine Extensions:** Adding new states or transitions to the task
  state machine.

## LIST OF EXAMPLE EXTENSIONS

| Extension | Description |
| :--- | :--- |
| **Secure Passport Extension** | Adds a trusted layer for immediate personalization (v1). |
| **Hello World Extension** | A simple extension demonstrating timestamp metadata (v1). |
| **Traceability Extension** | Python implementation and basic usage of Traceability (v1). |
| **Agent Gateway Protocol (AGP)** | A Routing Extension that introduces Autonomous Squads (v1). |

## LIMITATIONS

There are some changes to the protocol that extensions don't allow, primarily to
prevent breaking core type validations:

* **Changing the Definition of Core Data Structures:** For example, adding new
  fields or removing required fields to protocol-defined data structures.
  Extensions should place custom attributes in the metadata map present on core
  data structures.
* **Adding New Values to Enum Types:** Extensions should use existing enum
  values and annotate additional semantic meaning in the metadata field.

## EXTENSION DECLARATION

Agents declare their support for extensions in their Agent Card by including
`AgentExtension` objects within their `AgentCapabilities` object.

The following is an example of an Agent Card with an extension:

```json
{
  "name": "Magic 8-ball",
  "description": "An agent that can tell your future... maybe.",
  "version": "0.1.0",
  "url": "https://example.com/agents/eightball",
  "capabilities": {
    "streaming": true,
    "extensions": [
      {
        "uri": "https://example.com/ext/konami-code/v1",
        "description": "Provide cheat codes to unlock new fortunes",
        "required": false,
        "params": {
          "hints": [
            "When your sims need extra cash fast",
            "We've seen the evidence of those cows."
          ]
        }
      }
    ]
  },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "skills": [
    {
      "id": "fortune",
      "name": "Fortune teller",
      "description": "Seek advice from the mystical magic 8-ball",
      "tags": ["mystical", "untrustworthy"]
    }
  ]
}
```

## REQUIRED EXTENSIONS

While extensions generally offer optional functionality, some agents may have
stricter requirements. When an Agent Card declares an extension as
`required: true`, it signals to clients that some aspect of the extension
impacts how requests are structured or processed, and that the client must abide
by it. Agents shouldn't mark data-only extensions as required. If a client does
not request activation of a required extension, or fails to follow its protocol,
the agent should reject the incoming request with an appropriate error.

## EXTENSION SPECIFICATION

The detailed behavior and structure of an extension are defined by its
specification. While the exact format is not mandated, it should contain at
least:

* The specific URI(s) that identify the extension.
* The schema and meaning of objects specified in the `params` field of the
  `AgentExtension` object.
* Schemas of any additional data structures communicated between client and
  agent.
* Details of new request-response flows, additional endpoints, or any other
  logic required to implement the extension.

## EXTENSION DEPENDENCIES

Extensions might depend on other extensions. This can be a required dependency
(where the extension cannot function without the dependent) or an optional one
(where additional functionality is enabled if another extension is present).
Extension specifications should document these dependencies. It is the client's
responsibility to activate an extension and all its required dependencies as
listed in the extension's specification.

## EXTENSION ACTIVATION

Extensions default to being inactive, providing a baseline experience for
extension-unaware clients. Clients and agents perform negotiation to determine
which extensions are active for a specific request.

1. **Client Request:** A client requests extension activation by including the
   `A2A-Extensions` header in the HTTP request to the agent. The value is a
   comma-separated list of extension URIs the client intends to activate.
2. **Agent Processing:** Agents are responsible for identifying supported
   extensions in the request and performing the activation. Any requested
   extensions not supported by the agent can be ignored.
3. **Response:** Once the agent has identified all activated extensions, the
   response SHOULD include the `A2A-Extensions` header, listing all extensions
   that were successfully activated for that request.

Example request showing extension activation:

```http
POST /agents/eightball HTTP/1.1
Host: example.com
Content-Type: application/json
A2A-Extensions: https://example.com/ext/konami-code/v1
Content-Length: 519

{
  "jsonrpc": "2.0",
  "method": "SendMessage",
  "id": "1",
  "params": {
    "message": {
      "messageId": "1",
      "role": "ROLE_USER",
      "parts": [{"text": "Oh magic 8-ball, will it rain today?"}]
    },
    "metadata": {
      "https://example.com/ext/konami-code/v1/code": "motherlode"
    }
  }
}
```

Corresponding response echoing activated extensions:

```http
HTTP/1.1 200 OK
Content-Type: application/json
A2A-Extensions: https://example.com/ext/konami-code/v1
Content-Length: 338

{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "message": {
      "messageId": "2",
      "role": "ROLE_AGENT",
      "parts": [{"text": "That's a bingo!"}]
    }
  }
}
```

## IMPLEMENTATION CONSIDERATIONS

While the A2A protocol defines the functionality of extensions, this section
provides guidance on their implementation—best practices for authoring,
versioning, and distributing extension implementations.

* **Versioning:** Extension specifications evolve. It is crucial to have a
  clear versioning strategy to ensure that clients and agents can negotiate
  compatible implementations.
  * **Recommendation:** Use the extension's URI as the primary version
    identifier, ideally including a version number (for example,
    `https://example.com/ext/my-extension/v1`).
  * **Breaking Changes:** A new URI MUST be used when introducing a breaking
    change to an extension's logic, data structures, or required parameters.
  * **Handling Mismatches:** If a client requests a version not supported by the
    agent, the agent SHOULD ignore the activation request for that extension; it
    MUST NOT fall back to a different version.
* **Discoverability and Publication:**
  * **Specification Hosting:** The extension specification document should be
    hosted at the extension's URI.
  * **Permanent Identifiers:** Authors are encouraged to use a permanent
    identifier service, such as w3id.org, for their extension URIs to prevent
    broken links.
  * **Community Registry (Future):** The A2A community might establish a
    central registry for discovering and browsing available extensions in the
    future.
* **Packaging and Reusability (A2A SDKs and Libraries):** To promote adoption,
  extension logic should be packaged into reusable libraries that can be
  integrated into existing A2A client and server applications.
  * An extension implementation should be distributed as a standard package for
    its language ecosystem (for example, a PyPI package for Python, an npm
    package for TypeScript/JavaScript).
  * The objective is to provide a streamlined integration experience for
    developers. A well-designed extension package should allow a developer to
    add it to their server with minimal code.

Example Python implementation using `a2a.server`:

```python
import logging
import os
import click

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from agent import ReimbursementAgent
from agent_executor import ReimbursementAgentExecutor
from dotenv import load_dotenv
from timestamp_ext import TimestampExtension

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MissingAPIKeyError(Exception):
    """Exception for missing API key."""

@click.command()
@click.option('--host', default='localhost')
@click.option('--port', default=10002)
def main(host, port):
    try:
        # Check for API key only if Vertex AI is not configured
        if not os.getenv('GOOGLE_GENAI_USE_VERTEXAI') == 'TRUE':
            if not os.getenv('GEMINI_API_KEY'):
                raise MissingAPIKeyError(
                    'GEMINI_API_KEY environment variable not set'
                )

        hello_ext = TimestampExtension()
        capabilities = AgentCapabilities(
            streaming=True,
            extensions=[
                hello_ext.agent_extension(),
            ],
        )
        skill = AgentSkill(
            id='process_reimbursement',
            name='Process Reimbursement Tool',
            description='Helps with the reimbursement process.',
            tags=['reimbursement'],
            examples=[
                'Can you reimburse me $20 for my lunch?'
            ],
        )
        agent_card = AgentCard(
            name='Reimbursement Agent',
            description='This agent handles the reimbursement process.',
            url=f'http://{host}:{port}/',
            version='1.0.0',
            default_input_modes=ReimbursementAgent.SUPPORTED_CONTENT_TYPES,
            default_output_modes=ReimbursementAgent.SUPPORTED_CONTENT_TYPES,
            capabilities=capabilities,
            skills=[skill],
        )
        agent_executor = ReimbursementAgentExecutor()
        # Use the decorator version of the extension for ease of use.
        agent_executor = hello_ext.wrap_executor(agent_executor)
        request_handler = DefaultRequestHandler(
            agent_executor=agent_executor,
            task_store=InMemoryTaskStore(),
        )
        server = A2AStarletteApplication(
            agent_card=agent_card, http_handler=request_handler
        )
        import uvicorn

        uvicorn.run(server.build(), host=host, port=port)
    except MissingAPIKeyError as e:
        logger.error(f'Error: {e}')
        exit(1)
    except Exception as e:
        logger.error(f'An error occurred: {e}')
        exit(1)

if __name__ == '__main__':
    main()
```

* **Security:** Extensions modify core behavior and introduce new
  security considerations:
  * **Input Validation:** Any new fields or methods introduced by an extension
    MUST be rigorously validated. Treat all extension data as untrusted.
  * **Scope of Required Extensions:** Be mindful when marking an extension as
    `required: true`. It creates a hard dependency for all clients and should
    only be used for fundamental extensions (e.g., signing).
  * **Authentication and Authorization:** If an extension adds new methods, they
    MUST be subject to the same security checks as core A2A methods.
    Extensions MUST NOT bypass primary security controls.
