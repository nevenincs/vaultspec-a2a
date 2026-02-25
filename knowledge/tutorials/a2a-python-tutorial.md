---
title: A2A Python SDK Tutorial: Building an A2A Agent
source: https://a2a-protocol.org/latest/tutorials/python/
relevance: 10
---

# A2A Python SDK Tutorial: Building an A2A Agent

This tutorial provides a comprehensive guide to building and interacting with A2A-compliant agents using the Python SDK. It covers everything from environment setup to advanced streaming and multi-turn interactions.

## 1. Introduction

Welcome to the Agent2Agent (A2A) Python Quickstart Tutorial! This guide introduces the fundamental concepts and components of an A2A server using a simple "echo" example, followed by a more advanced integration with a Large Language Model (LLM).

**Key Learning Objectives:**
- Basic concepts of the A2A protocol.
- Setting up a Python environment for A2A development.
- Describing agents using Agent Skills and Agent Cards.
- Handling tasks with an A2A server.
- Interacting with an A2A server using a client.
- Implementing streaming and multi-turn interactions.
- Integrating LLMs into A2A agents.

---

## 2. Setup Your Environment

### Prerequisites
- Python 3.10 or higher.
- Terminal/Command Prompt access.
- Git (for cloning the repository).
- Code editor (e.g., VS Code).

### Clone the Repository
```powershell
git clone https://github.com/a2aproject/a2a-samples.git -b main --depth 1
cd a2a-samples
```

### Python Environment & SDK Installation
It is recommended to use a virtual environment. The A2A Python SDK supports `uv` and `pip`.

**Using venv:**
```powershell
# Windows
python -m venv .venv
.\.venv\Scripts\activate

# Mac/Linux
python -m venv .venv
source .venv/bin/activate
```

**Install Dependencies:**
```powershell
pip install -r samples/python/requirements.txt
```

### Verify Installation
```powershell
python -c "import a2a; print('A2A SDK imported successfully')"
```

---

## 3. Agent Skills & Agent Card

Agents must define their capabilities (Skills) and how they can be discovered (Agent Card).

### Agent Skills
An `AgentSkill` describes a specific function. Key attributes include `id`, `name`, `description`, `tags`, `examples`, and `inputModes`/`outputModes`.

**Example Skill Definition:**
```python
from a2a.types import AgentSkill

skill = AgentSkill(
    id='hello_world',
    name='Returns hello world',
    description='just returns hello world',
    tags=['hello world'],
    examples=['hi', 'hello world'],
)
```

### Agent Card
The Agent Card is a JSON document (typically at `.well-known/agent-card.json`) acting as a digital business card.

**Example Agent Card Definition:**
```python
from a2a.types import AgentCard, AgentCapabilities

public_agent_card = AgentCard(
    name='Hello World Agent',
    description='Just a hello world agent',
    url='http://localhost:9999/',
    version='1.0.0',
    default_input_modes=['text'],
    default_output_modes=['text'],
    capabilities=AgentCapabilities(streaming=True),
    skills=[skill],
    supports_authenticated_extended_card=True,
)
```

---

## 4. The Agent Executor

The `AgentExecutor` handles the core logic of processing requests and generating responses.

### AgentExecutor Interface
You must implement the `a2a.server.agent_execution.AgentExecutor` abstract base class:
- `async def execute(self, context: RequestContext, event_queue: EventQueue)`: Processes inputs and enqueues events (Messages, Tasks, Status Updates).
- `async def cancel(self, context: RequestContext, event_queue: EventQueue)`: Handles task cancellation.

### HelloWorld Agent Executor Implementation
```python
from a2a.server.agent_execution import AgentExecutor
from a2a.server.context import RequestContext
from a2a.server.events import EventQueue
from a2a.server.utils import new_agent_text_message

class HelloWorldAgent:
    async def invoke(self) -> str:
        return 'Hello World'

class HelloWorldAgentExecutor(AgentExecutor):
    def __init__(self):
        self.agent = HelloWorldAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        result = await self.agent.invoke()
        await event_queue.enqueue_event(new_agent_text_message(result))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception('cancel not supported')
```

---

## 5. Starting the Server

The SDK provides `A2AStarletteApplication` to run an A2A-compliant HTTP server.

### Server Setup (`__main__.py`)
```python
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from agent_executor import HelloWorldAgentExecutor

# ... (Skill and AgentCard definitions from Section 3)

request_handler = DefaultRequestHandler(
    agent_executor=HelloWorldAgentExecutor(),
    task_store=InMemoryTaskStore(),
)

server = A2AStarletteApplication(
    agent_card=public_agent_card,
    http_handler=request_handler,
    extended_agent_card=specific_extended_agent_card, # Optional
)

if __name__ == '__main__':
    uvicorn.run(server.build(), host='0.0.0.0', port=9999)
```

### Running the Server
```powershell
python samples/python/agents/helloworld/__main__.py
```

---

## 6. Interacting with the Server

Use `A2AClient` to simplify interactions.

### Fetching Card & Initializing Client
```python
from a2a.client import A2AClient, A2ACardResolver
import httpx

base_url = 'http://localhost:9999'
async with httpx.AsyncClient() as httpx_client:
    resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
    # ... resolver fetches card and initializes client
```

### Sending a Message (Non-Streaming)
```python
from a2a.types import SendMessageRequest, MessageSendParams
from uuid import uuid4

send_message_payload = {
    'message': {
        'role': 'user',
        'parts': [{'kind': 'text', 'text': 'how much is 10 USD in INR?'}],
        'messageId': uuid4().hex,
    },
}
request = SendMessageRequest(id=str(uuid4()), params=MessageSendParams(**send_message_payload))
response = await client.send_message(request)
print(response.model_dump(mode='json', exclude_none=True))
```

### Sending a Streaming Message
```python
from a2a.types import SendStreamingMessageRequest

streaming_request = SendStreamingMessageRequest(id=str(uuid4()), params=MessageSendParams(**send_message_payload))
stream_response = client.send_message_streaming(streaming_request)
async for chunk in stream_response:
    print(chunk.model_dump(mode='json', exclude_none=True))
```

---

## 7. Streaming & Multi-Turn Interactions (LangGraph Example)

For advanced features, refer to the LangGraph example in `samples/python/agents/langgraph/`.

### Key Concepts Demonstrated:
1.  **LLM Integration**: Uses `ChatGoogleGenerativeAI` and LangGraph's `create_react_agent`.
2.  **Task State Management**: Uses `InMemoryTaskStore` to persist state across interactions.
3.  **Streaming Events**:
    - `TaskStatusUpdateEvent`: Intermediate updates (e.g., "Looking up exchange rates...").
    - `TaskArtifactUpdateEvent`: Final answer chunks.
4.  **Multi-Turn Conversation**:
    - Agent returns `TaskState.input_required` for ambiguous queries.
    - Client continues the task by providing `taskId` and `contextId` in subsequent messages.

### Running the LangGraph Server:
1.  Set `GOOGLE_API_KEY` in a `.env` file.
2.  Run `python __main__.py` in the langgraph app directory.
3.  Test with `python test_client.py`.

---

## 8. Next Steps

Congratulations! You have built a foundation for A2A development.

**Where to Go From Here:**
- **Explore Samples**: Check `a2a-samples` for complex integrations.
- **Deepen Knowledge**: Read the [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/).
- **Build Custom Agents**: Integrate frameworks like LangChain, CrewAI, or AutoGen.
- **Advanced Features**: Implement persistent `TaskStore`, push notifications, and complex input/output modalities (file/data Parts).
- **Contribute**: Join the A2A community on GitHub.
