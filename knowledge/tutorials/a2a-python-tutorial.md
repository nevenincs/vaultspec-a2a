---
title: A2A Python SDK Tutorial
source: https://a2a-protocol.org/latest/tutorials/python/
relevance: 10
---

# A2A Python SDK Tutorial: Building an A2A Agent

This tutorial walks through building an A2A-compliant agent using the Python SDK, from setup to advanced streaming and multi-turn interactions.

## 1. Introduction[1]

This tutorial demonstrates the concepts and components of an A2A server, starting with a simple "echo" example and progressing to an LLM-integrated agent.

### Key Concepts

- **Agent:** An autonomous system capable of reasoning and using tools.
- **Protocol:** Defines how agents communicate (A2A).
- **Skills & Cards:** How agents advertise their capabilities.
- **Executor:** The runtime logic of the agent.

---

## 2. Setup[2]

### Prerequisites

- Python 3.10+
- Terminal access
- Git

### Clone the Repository

```powershell
git clone https://github.com/a2aproject/a2a-samples.git -b main --depth 1
cd a2a-samples
```

### Create Environment

Using `venv` is recommended.

**Windows:**

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

**Mac/Linux:**

```bash
python -m venv .venv
source .venv/bin/activate
```

### Install Dependencies

```powershell
pip install -r samples/python/requirements.txt
```

### Verify Installation

```powershell
python -c "import a2a; print('A2A SDK imported successfully')"
```

---

## 3. Agent Skills & Agent Card[3]

Agents must define what they can do (Skills) and how they are discovered (Card).

### Define a Skill

An `AgentSkill` describes a discrete capability.

```python
from a2a.types import AgentSkill

skill = AgentSkill(
    id='hello_world',
    name='Returns hello world',
    description='just returns hello world',
    tags=['hello world'],
    examples=['hi', 'hello world'],
    input_modes=['text'],  # Expected input MIME type (e.g., text/plain)
    output_modes=['text'], # Expected output MIME type
)
```

### Define the Agent Card

The `AgentCard` acts as the agent's manifest.

```python
from a2a.types import AgentCard, AgentCapabilities

public_agent_card = AgentCard(
    name='Hello World Agent',
    description='Just a hello world agent',
    url='http://localhost:9999/',
    version='1.0.0',
    default_input_modes=['text'],
    default_output_modes=['text'],
    capabilities=AgentCapabilities(
        streaming=True,            # Supports SSE streaming
        push_notifications=False,  # Supports Webhooks
        extended_agent_card=True   # Supports authenticated card retrieval
    ),
    skills=[skill],
    supports_authenticated_extended_card=True,
)
```

---

## 4. The Agent Executor[4]

The `AgentExecutor` implements the agent's logic. You must subclass `a2a.server.agent_execution.AgentExecutor` and implement `execute` and `cancel`.

### Implementation: Hello World Agent

This executor simply echoes "Hello World".

```python
from a2a.server.agent_execution import AgentExecutor
from a2a.server.context import RequestContext
from a2a.server.events import EventQueue
from a2a.server.utils import new_agent_text_message

class HelloWorldAgent:
    """Mock agent logic."""
    async def invoke(self) -> str:
        return 'Hello World'

class HelloWorldAgentExecutor(AgentExecutor):
    def __init__(self):
        self.agent = HelloWorldAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """
        Main execution loop.
        1. Invokes the agent logic.
        2. Wraps the result in an A2A Message.
        3. Enqueues the message to be sent to the client.
        """
        result = await self.agent.invoke()

        # Create a standard text message response
        message_event = new_agent_text_message(result)

        # Enqueue the event for delivery
        await event_queue.enqueue_event(message_event)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Handle cancellation requests."""
        raise Exception('cancel not supported')
```

---

## 5. Starting the Server[5]

The SDK provides `A2AStarletteApplication` to serve the agent over HTTP.

### Server Script (`__main__.py`)

```python
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
# Import your executor and card definitions here
# from agent_executor import HelloWorldAgentExecutor
# from definitions import public_agent_card

# 1. Initialize Request Handler
# DefaultRequestHandler manages task persistence and execution flow.
request_handler = DefaultRequestHandler(
    agent_executor=HelloWorldAgentExecutor(),
    task_store=InMemoryTaskStore(), # Stores tasks in RAM (lost on restart)
)

# 2. Configure the Application
server = A2AStarletteApplication(
    agent_card=public_agent_card,
    http_handler=request_handler,
    # extended_agent_card=... (Optional: for authenticated clients)
)

# 3. Run with Uvicorn
if __name__ == '__main__':
    uvicorn.run(server.build(), host='0.0.0.0', port=9999)
```

Run the server:

```powershell
python samples/python/agents/helloworld/__main__.py
```

_The server will start at `http://0.0.0.0:9999`._

---

## 6. Interacting with the Server[6]

The `A2AClient` simplifies communication. It handles card resolution and RPC calls.

### Client Setup

```python
from a2a.client import A2AClient, A2ACardResolver
import httpx

base_url = 'http://localhost:9999'

async def main():
    async with httpx.AsyncClient() as httpx_client:
        # 1. Resolve the Agent Card
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
        client = await resolver.resolve()

        print(f"Connected to: {client.agent_card.name}")
```

### Sending a Message (Task)

```python
from a2a.types import SendMessageRequest, MessageSendParams
from uuid import uuid4

# ... inside async function ...

# Create payload
send_message_payload = {
    'message': {
        'role': 'user',
        'parts': [{'kind': 'text', 'text': 'Hello?'}],
        'messageId': uuid4().hex,
    },
}

# Wrap in Request object
request = SendMessageRequest(
    id=str(uuid4()),
    params=MessageSendParams(**send_message_payload)
)

# Send and await response
response = await client.send_message(request)
print("Response:", response.model_dump(mode='json', exclude_none=True))
```

---

## 7. Streaming and Multi-Turn (Advanced)[7]

Real-world agents often stream partial results and require multiple turns (e.g., clarifying questions).

### Streaming

Use `SendStreamingMessageRequest` to receive chunks.

```python
from a2a.types import SendStreamingMessageRequest

streaming_request = SendStreamingMessageRequest(
    id=str(uuid4()),
    params=MessageSendParams(**send_message_payload)
)

stream_response = client.send_message_streaming(streaming_request)

async for chunk in stream_response:
    # Chunk can be a TaskStatusUpdate, ArtifactUpdate, or Message
    print("Chunk:", chunk.model_dump(mode='json', exclude_none=True))
```

### Multi-Turn Logic (LangGraph Example)

The SDK supports multi-turn workflows where the agent pauses for input (`INPUT_REQUIRED`).

1.  **Agent Pauses:** Returns `TaskState.input_required` when it needs clarification.
2.  **Client Responds:** Sends a new message with the **same `taskId`** and `contextId`.
3.  **Agent Resumes:** The `AgentExecutor` retrieves the task history and continues.

**Example Flow:**

1.  User: "Book a flight."
2.  Agent (Stream): `TaskStatusUpdate(state='working')` -> `TaskStatusUpdate(state='input_required')` -> `Message("Where to?")`.
3.  User: (Sends message with `taskId` from step 2) "To Paris."
4.  Agent: `TaskStatusUpdate(state='completed')` -> `Message("Booked flight to Paris.")`.

---

## 8. Next Steps[8]

- **Explore Samples:** `samples/python/agents/` contains robust examples like `langgraph` (LLM integration) and `autogen`.
- **Read the Spec:** Understand the underlying protocol messages.
- **Implement Persistence:** Replace `InMemoryTaskStore` with a database-backed store for production.
- **Add Push Notifications:** Implement webhooks for long-running tasks.

Sources:
[1] https://a2a-protocol.org/latest/tutorials/python/1-introduction
[2] https://a2a-protocol.org/latest/tutorials/python/2-setup/
[3] https://a2a-protocol.org/latest/tutorials/python/3-agent-skills-and-card/
[4] https://a2a-protocol.org/latest/tutorials/python/4-agent-executor/
[5] https://a2a-protocol.org/latest/tutorials/python/5-start-server/
[6] https://a2a-protocol.org/latest/tutorials/python/6-interact-with-server/
[7] https://a2a-protocol.org/latest/tutorials/python/7-streaming-and-multiturn/
[8] https://a2a-protocol.org/latest/tutorials/python/8-next-steps/
