"""Provide the separate FastAPI execution process.

Worker modules define the application factory, application type, graph
executor, and gateway inter-process bridge. Uvicorn starts the application;
this package doesn't provide a ``vaultspec-worker`` console command.

Execution uses :mod:`vaultspec_a2a.graph`, :mod:`vaultspec_a2a.providers`, and
:mod:`vaultspec_a2a.streaming`. Gateway communication follows
:mod:`vaultspec_a2a.ipc`.

Authoring integration lives in
:mod:`vaultspec_a2a.worker.authoring_binding`. Execution also uses
:mod:`vaultspec_a2a.authoring` and :mod:`vaultspec_a2a.database`.
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
