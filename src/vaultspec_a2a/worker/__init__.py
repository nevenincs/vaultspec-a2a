"""Agent Worker -- LangGraph execution engine (ADR-019).

Runs as a separate process from the gateway.
Communicates via HTTP POST (events/heartbeats -> API) and HTTP
(dispatch -> worker).

Public API
----------
WorkerApp
    Type alias for the worker's ``FastAPI`` instance.
create_worker_app
    Factory function that builds and returns the worker app.
main
    CLI entry point for the ``vaultspec-worker`` console script.
Executor
    Graph execution engine used internally by the worker app.
WorkerBridge
    HTTP-based IPC bridge used internally by the worker app.
"""

from .app import WorkerApp, create_worker_app, main
from .executor import Executor
from .ipc import WorkerBridge

__all__ = [
    "Executor",
    "WorkerApp",
    "WorkerBridge",
    "create_worker_app",
    "main",
]
