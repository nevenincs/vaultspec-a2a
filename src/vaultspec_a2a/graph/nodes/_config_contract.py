"""Make a node's ``config`` parameter visible to LangGraph's injector.

LangGraph decides whether to pass ``config`` into a node by reading the
parameter's annotation off ``inspect.signature`` and testing membership in a
fixed set: ``RunnableConfig``, ``"RunnableConfig"``, ``Optional[RunnableConfig]``,
``"Optional[RunnableConfig]"``, or no annotation at all. Anything else is warned
about once and then SKIPPED, so the node is invoked with no config.

Every node module here carries ``from __future__ import annotations`` - kept for
import latency - which stringizes annotations at definition time. A modern
``config: RunnableConfig | None`` therefore reaches the injector as the string
``"RunnableConfig | None"``, which is not in that set, so config injection was
silently dropped for every node in this package. The symptom is easy to misread
as unrelated: with no config there are no callbacks, so no ``on_chat_model_*``
event is ever emitted for a graph turn even though the model runs and returns
real content, and thread id, tags, and run metadata never reach the provider
call either.

Stamping the REAL union object onto ``__annotations__`` after definition is what
restores it. ``RunnableConfig | None == Optional[RunnableConfig]`` is true, so
the injector's membership test passes on the live type while the source keeps
the modern spelling - no ``Optional`` import, and nothing for pyupgrade to
rewrite back into the broken form.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.runnables import RunnableConfig

if TYPE_CHECKING:
    from collections.abc import Callable

#: The annotation LangGraph's injector accepts, built once as a live object
#: rather than a string so the membership test in its runnable wrapper matches.
RUNNABLE_CONFIG_ANNOTATION = RunnableConfig | None


def accepting_runnable_config[NodeT: Callable[..., object]](node: NodeT) -> NodeT:
    """Return *node* with a ``config`` annotation LangGraph will honour.

    A no-op for a node that declares no ``config`` parameter, so it is safe to
    apply at any factory's return without first checking the signature. The node
    itself is returned, not a wrapper: wrapping would change the very signature
    the injector reads.
    """
    annotations = getattr(node, "__annotations__", None)
    if isinstance(annotations, dict) and "config" in annotations:
        annotations["config"] = RUNNABLE_CONFIG_ANNOTATION
    return node
