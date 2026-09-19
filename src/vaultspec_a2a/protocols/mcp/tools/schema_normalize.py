"""Normalize the engine catalog's input schema to valid MCP JSON Schema.

The pinned CLI validates a tool's ``inputSchema`` as JSON Schema and SILENTLY
DROPS non-conforming tools after connecting - the "connected but not exposed"
root cause. This module guarantees a valid JSON Schema object at the
bridge serving boundary, handling BOTH engine generations without knowing which
one it is talking to (version skew):

- **Valid-schema pass-through.** A newer engine serves the model-owned content as
  standard, valid JSON Schema (top-level ``type: object`` with a ``properties``
  map). Detection is STRUCTURAL - validate the shape, do not guess from the tool
  name. Such a schema is passed through VERBATIM, save for two adjustments: the
  dispatcher-injected id fields are stripped wherever they appear (nested
  included), and guidance is appended.
- **DSL translation (fallback).** An older engine serves a custom DSL, not JSON
  Schema: no top-level ``type: object`` / ``properties`` and invented keywords
  (``oneOf`` branches carrying ``target`` / ``operation`` / ``required`` /
  ``optional``, ``bounds``, ``alias_of``, ``backend_derived``, ``payload``,
  ``composes``). Each such schema is translated into a valid JSON Schema object,
  its per-branch requirements / bounds / dropped keywords summarized into
  guidance.

Design posture: the ENGINE remains the execution-time authority (server-side
validation + human-approval gating). The normalized schema's job is to REGISTER
the tool (so the CLI keeps it) and GUIDE the model (field names, discriminators,
bounds as prose) - NOT to enforce the schema's full semantics. The original
catalog schema is never mutated; normalization happens only at serving time.
"""

from __future__ import annotations

import copy
from typing import Any, cast

__all__ = ["normalize_tool_input_schema"]

# oneOf-branch keys whose value is a scalar branch discriminator (not a field).
_DISCRIMINATOR_KEYS = ("target", "operation")
# Top-level DSL keys the translator consumes directly; anything else is unknown
# and summarized into guidance rather than emitted as schema.
_CONSUMED_KEYS = frozenset(
    {
        "oneOf",
        "required",
        "optional",
        "bounds",
        "additionalProperties",
        "type",
        "properties",
    }
)


def _permissive_field() -> dict[str, Any]:
    # The DSL carries no per-field type, so fields are typed permissively; the
    # engine validates the real shape at execution time.
    return {"type": "string"}


def _str_list(value: object, exclude: frozenset[str] = frozenset()) -> list[str]:
    """Return the string members of *value* (a list), minus any in *exclude*."""
    if not isinstance(value, list):
        return []
    items = cast("list[object]", value)
    return [item for item in items if isinstance(item, str) and item not in exclude]


def _looks_like_json_schema(raw: dict[str, Any]) -> bool:
    """Whether *raw* is ALREADY a valid JSON Schema object.

    A newer engine serves the model-owned content as standard JSON Schema
    (top-level ``type: object`` with a ``properties`` map); an older engine
    serves the custom DSL (``oneOf`` / ``required`` / ``bounds`` with no top-level
    ``type``). This structural test - not the tool name - selects the
    pass-through path over the DSL translation, so version skew is handled
    without knowing which engine served the catalog.
    """
    return raw.get("type") == "object" and isinstance(raw.get("properties"), dict)


def _strip_injected_properties(
    node_map: dict[str, object], injected: frozenset[str]
) -> None:
    properties = node_map.get("properties")
    if isinstance(properties, dict):
        properties_map = cast("dict[str, object]", properties)
        for name in list(properties_map):
            if name in injected:
                del properties_map[name]
            else:
                _deep_strip_injected(properties_map[name], injected)
    required = node_map.get("required")
    if isinstance(required, list):
        required_list = cast("list[object]", required)
        node_map["required"] = [item for item in required_list if item not in injected]


def _strip_injected_children(
    node_map: dict[str, object], injected: frozenset[str]
) -> None:
    for key in ("items", "additionalProperties"):
        child = node_map.get(key)
        if isinstance(child, (dict, list)):
            _deep_strip_injected(child, injected)
    for key in ("oneOf", "anyOf", "allOf"):
        branches = node_map.get(key)
        if isinstance(branches, list):
            for branch in cast("list[object]", branches):
                _deep_strip_injected(branch, injected)


def _strip_injected_from_object(
    node_map: dict[str, object], injected: frozenset[str]
) -> None:
    _strip_injected_properties(node_map, injected)
    _strip_injected_children(node_map, injected)


def _deep_strip_injected(node: Any, injected: frozenset[str]) -> None:
    """Remove dispatcher-owned names recursively from a copied schema."""
    if isinstance(node, dict):
        _strip_injected_from_object(cast("dict[str, object]", node), injected)
    elif isinstance(node, list):
        for item in cast("list[object]", node):
            _deep_strip_injected(item, injected)


def _passthrough_valid_schema(
    raw: dict[str, Any], injected: frozenset[str]
) -> tuple[dict[str, Any], str]:
    """Pass an already-valid engine schema through, minus the injected ids.

    The schema is preserved VERBATIM (nested shape intact - the model sees the
    real structure it must construct) except that the dispatcher-injected id
    fields are stripped wherever they appear. Guidance names the withheld fields
    so the model's contract records why they are absent; the schema's own
    ``description`` (e.g. the engine's scoped-follow-up note) rides through
    verbatim and is not duplicated here.
    """
    schema = copy.deepcopy(raw)
    _deep_strip_injected(schema, injected)
    guidance = ""
    if injected:
        guidance = (
            "Injected below the model by the dispatcher (do not supply): "
            + ", ".join(sorted(injected))
            + "."
        )
    return schema, guidance


def _merge_properties(
    target: dict[str, Any], provided: object, injected: frozenset[str]
) -> None:
    """Merge a schema's own ``properties`` into *target*, minus injected fields.

    When the engine inlines model-owned content as JSON Schema (e.g. the
    create branch's ``operations`` array), that nested structure is preserved
    VERBATIM rather than collapsed to a permissive field - so the model sees the
    real shape it must construct. Injected (dispatcher-owned) names are dropped.
    """
    if not isinstance(provided, dict):
        return
    provided_map = cast("dict[object, object]", provided)
    for name, subschema in provided_map.items():
        if not isinstance(name, str) or name in injected:
            continue
        if isinstance(subschema, dict):
            target[name] = subschema


def _branch_discriminator_note(
    branch: dict[str, Any],
    note_parts: list[str],
    enum_values: dict[str, list[str]],
) -> str | None:
    for key in _DISCRIMINATOR_KEYS:
        value: object = branch.get(key)
        if isinstance(value, str):
            values = enum_values.setdefault(key, [])
            if value not in values:
                values.append(value)
            detail = "; ".join(note_parts) if note_parts else "no fields"
            return f"{key}={value!r} {detail}"
    return None


def _oneof_branch_note(
    branch: dict[str, Any],
    required: list[str],
    optional: list[str],
    enum_values: dict[str, list[str]],
) -> tuple[str | None, bool]:
    """Collect a branch's discriminator guidance and opaque-shape signal."""
    payload: object = branch.get("payload")
    alias_of: object = branch.get("alias_of")
    note_parts: list[str] = []
    if required:
        note_parts.append("requires " + ", ".join(required))
    if isinstance(payload, str):
        note_parts.append(f"sends payload {payload}")
    opaque_alias = isinstance(alias_of, str) and not (required or optional)
    if opaque_alias:
        note_parts.append(f"input aliases {alias_of}")
    return (
        _branch_discriminator_note(branch, note_parts, enum_values),
        isinstance(payload, str) or opaque_alias,
    )


def _translate_oneof_schema(
    branches: list[Any], injected: frozenset[str]
) -> tuple[dict[str, Any], list[str], list[str], bool]:
    """Translate a ``oneOf`` DSL schema into JSON-Schema fragments.

    Returns the accumulated ``(properties, required, guidance_parts, open_schema)``.
    A branch carrying an opaque payload or an unenumerated alias leaves the schema
    open, because the engine flattens those fields the DSL does not name.
    """
    properties: dict[str, Any] = {}
    open_schema = False
    required_sets: list[set[str]] = []
    enum_values: dict[str, list[str]] = {}
    branch_notes: list[str] = []
    for branch_raw in branches:
        if not isinstance(branch_raw, dict):
            continue
        branch = cast("dict[str, Any]", branch_raw)
        b_required = _str_list(branch.get("required"), injected)
        b_optional = _str_list(branch.get("optional"), injected)
        for field in (*b_required, *b_optional):
            properties.setdefault(field, _permissive_field())
        # A branch that inlines its own JSON-Schema properties (engine content
        # inlining) contributes them verbatim, overriding the permissive
        # placeholders above with the real nested shape.
        _merge_properties(properties, branch.get("properties"), injected)
        required_sets.append(set(b_required))
        note, opaque = _oneof_branch_note(branch, b_required, b_optional, enum_values)
        open_schema = open_schema or opaque
        if note is not None:
            branch_notes.append(note)
    for disc_key, values in enum_values.items():
        properties[disc_key] = {"type": "string", "enum": values}
    # Per-branch required sets differ, so the top-level guarantee is their
    # intersection (often empty); per-branch requirements ride the guidance.
    required: list[str] = []
    if required_sets:
        required = sorted(required_sets[0].intersection(*required_sets[1:]))
    guidance_parts: list[str] = []
    if branch_notes:
        guidance_parts.append("One of: " + "; ".join(branch_notes) + ".")
    return properties, required, guidance_parts, open_schema


def _translate_flat_schema(
    raw: dict[str, Any], injected: frozenset[str]
) -> tuple[dict[str, Any], list[str], bool]:
    """Translate a flat (non-``oneOf``) DSL schema into JSON-Schema fragments.

    Returns ``(properties, required, open_schema)``. A top-level opaque payload
    leaves the schema open, as in the branch case.
    """
    properties: dict[str, Any] = {}
    b_required = _str_list(raw.get("required"), injected)
    b_optional = _str_list(raw.get("optional"), injected)
    for field in (*b_required, *b_optional):
        properties.setdefault(field, _permissive_field())
    _merge_properties(properties, raw.get("properties"), injected)
    required = sorted(b_required)
    # A top-level opaque payload (e.g. request_apply -> ApplyRequest) has no
    # enumerated fields, so the schema must stay open for the model to send it.
    open_schema = isinstance(raw.get("payload"), str)
    return properties, required, open_schema


def normalize_tool_input_schema(
    raw: object, injected: frozenset[str] = frozenset()
) -> tuple[dict[str, Any], str]:
    """Normalize one catalog ``input_schema`` to ``(json_schema, guidance)``.

    ``json_schema`` is always a valid JSON Schema object. When *raw* is already a
    valid JSON Schema (top-level ``type: object`` with ``properties``, the newer
    engine), it is passed through verbatim minus the injected ids; otherwise the
    custom DSL is translated (the fallback for an older engine). ``guidance`` is
    prose the caller appends to the tool description so the withheld ids,
    per-branch requirements, bounds, and dropped engine keywords still reach the
    model. A non-dict input yields a bare object schema.

    *injected* names the fields the dispatcher owns and injects run-scoped
    (session_id / changeset_id / expected_revision / approval_id for a proposal
    command). They are removed from properties, required, and the branch guidance
    so they never appear in the model's contract - the model must not, and cannot,
    supply them. Read tools pass an empty set, keeping their target ids
    model-owned.
    """
    if not isinstance(raw, dict):
        return {"type": "object"}, ""
    raw_map = cast("dict[str, Any]", raw)

    if _looks_like_json_schema(raw_map):
        return _passthrough_valid_schema(raw_map, injected)

    branches_raw: object = raw_map.get("oneOf")
    if isinstance(branches_raw, list) and branches_raw:
        branches = cast("list[Any]", branches_raw)
        properties, required, guidance_parts, open_schema = _translate_oneof_schema(
            branches, injected
        )
    else:
        properties, required, open_schema = _translate_flat_schema(raw_map, injected)
        guidance_parts = []

    bounds_raw: object = raw_map.get("bounds")
    if isinstance(bounds_raw, dict) and bounds_raw:
        bounds = cast("dict[str, Any]", bounds_raw)
        guidance_parts.append(
            "Bounds: " + ", ".join(f"{k}={v}" for k, v in bounds.items()) + "."
        )

    unknown: dict[str, Any] = {
        k: v for k, v in raw_map.items() if k not in _CONSUMED_KEYS
    }
    if unknown:
        guidance_parts.append(
            "Engine: " + "; ".join(f"{k}={v}" for k, v in unknown.items()) + "."
        )

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    # A tool carrying an opaque payload must stay OPEN so the model can send the
    # engine-flattened payload fields the DSL does not enumerate; only tools whose
    # fields are fully enumerated get the closed guarantee.
    if not open_schema:
        schema["additionalProperties"] = False
    if required:
        schema["required"] = required
    return schema, " ".join(guidance_parts)
