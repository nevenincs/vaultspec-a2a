"""Strict JSON readers used only by test-side provider response checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....providers._json_contract import JsonValue

__all__ = ["json_list", "json_text"]


def json_list(value: JsonValue, *, at: str = "value") -> list[JsonValue]:
    """Return *value* as a JSON array, or raise naming what it actually was."""
    if not isinstance(value, list):
        msg = f"expected a JSON array at {at}, got {type(value).__name__}"
        raise TypeError(msg)
    return value


def json_text(value: JsonValue, *, at: str = "value") -> str:
    """Return *value* as a JSON string, or raise naming what it actually was."""
    if not isinstance(value, str):
        msg = f"expected a JSON string at {at}, got {type(value).__name__}"
        raise TypeError(msg)
    return value
