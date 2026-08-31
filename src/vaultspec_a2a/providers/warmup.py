"""Pay the model stack's import cost somewhere other than an event loop.

:meth:`ProviderFactory.create` imports ``langchain_openai`` and this package's
``acp_chat_model`` lazily and unconditionally, because the classification and
readiness helpers beside it answer questions that need no model at all and must
not load one to do so. That laziness is correct and stays. What was wrong is
WHERE the deferred cost was finally paid: ``create`` is reached from
``compile_team_graph`` and the armed-preset attachment gate, both synchronous,
both running directly on the worker's event loop during the first compile of a
run. Measured cold on this project's environment, ``langchain_openai`` costs
about 6.4s (it resolves ``BaseChatModel`` through ``transformers``, whose
package ``__init__`` walks its whole model tree) and ``acp_chat_model`` about
0.6s (it reaches ``mcp``, whose type module rebuilds its Pydantic schemas at
import). For that whole window the loop ran no callbacks, so the worker answered
neither ``/health`` nor a second dispatch while it was, from the outside,
silently booting a run.

Warming is nothing more than performing those same imports from a thread. It
holds no state and is not a cache: ``sys.modules`` is the cache, which makes a
second call a dict lookup and lets every caller treat this as free once warm.
Failures propagate rather than being absorbed, because an import that cannot
succeed here will fail identically inside ``create`` moments later, and a
swallowed error would only delay the truthful report.
"""

from __future__ import annotations

import importlib
from typing import Final

__all__ = ["MODEL_STACK_MODULES", "warm_model_imports"]

#: The modules :meth:`ProviderFactory.create` imports before it branches on the
#: requested provider - so every lane, including the in-process ones, pays for
#: all of them. Provider-specific model modules are deliberately absent: each
#: measured at or below 15ms cold, which is not worth pre-loading a lane the run
#: may never select.
MODEL_STACK_MODULES: Final[tuple[str, ...]] = (
    "langchain_openai",
    ".acp_chat_model",
)


def warm_model_imports() -> None:
    """Import the model stack, blocking the calling thread until it is loaded.

    Safe to call from any thread and any number of times. Callers on an event
    loop must offload it (``asyncio.to_thread`` / ``anyio.to_thread.run_sync``);
    calling it on the loop reproduces exactly the stall it exists to remove.
    """
    for module in MODEL_STACK_MODULES:
        importlib.import_module(module, __package__ if module.startswith(".") else None)
