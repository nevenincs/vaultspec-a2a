"""Typed legacy option binder for graph lifecycle construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from .catalog_store import RunCatalogStore
    from .token_store import RunTokenStore


class _GraphLifecycleRequired(TypedDict):
    token_store: RunTokenStore
    catalog_store: RunCatalogStore


class GraphLifecycleOptions(_GraphLifecycleRequired, total=False):
    checkpoint_read_timeout_seconds: float | None


_GRAPH_OPTION_MISSING = object()
_GRAPH_OPTION_NAMES = frozenset(
    {"token_store", "catalog_store", "checkpoint_read_timeout_seconds"}
)


def _graph_option_value(
    args: tuple[object, ...],
    index: int,
    name: str,
    options: GraphLifecycleOptions,
    *,
    default: object = _GRAPH_OPTION_MISSING,
) -> object:
    if index < len(args) and name in options:
        raise TypeError(
            "GraphLifecycleManager.__init__() got multiple values for "
            f"argument {name!r}"
        )
    if index < len(args):
        return args[index]
    return options.get(name, default)


def _reject_unknown_graph_options(options: GraphLifecycleOptions) -> None:
    unknown = next((name for name in options if name not in _GRAPH_OPTION_NAMES), None)
    if unknown is not None:
        raise TypeError(
            "GraphLifecycleManager.__init__() got an unexpected keyword "
            f"argument {unknown!r}"
        )


def bind_graph_lifecycle_options(
    args: tuple[object, ...], options: GraphLifecycleOptions
) -> tuple[RunTokenStore, RunCatalogStore, float | None]:
    """Bind legacy positional and current keyword constructor arguments."""
    if len(args) > 3:
        raise TypeError(
            "GraphLifecycleManager.__init__() takes at most 6 positional "
            f"arguments ({len(args) + 4} given)"
        )
    _reject_unknown_graph_options(options)
    token_store_value = _graph_option_value(args, 0, "token_store", options)
    catalog_store_value = _graph_option_value(args, 1, "catalog_store", options)
    timeout_value = _graph_option_value(
        args, 2, "checkpoint_read_timeout_seconds", options, default=None
    )
    if token_store_value is _GRAPH_OPTION_MISSING:
        raise TypeError(
            "GraphLifecycleManager.__init__() missing required argument 'token_store'"
        )
    if catalog_store_value is _GRAPH_OPTION_MISSING:
        raise TypeError(
            "GraphLifecycleManager.__init__() missing required argument 'catalog_store'"
        )
    return (
        cast("RunTokenStore", token_store_value),
        cast("RunCatalogStore", catalog_store_value),
        cast("float | None", timeout_value),
    )
