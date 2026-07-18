"""Normalize the engine catalog's input-schema DSL to valid MCP JSON Schema.

The engine catalog's ``input_schema`` is a custom DSL, not JSON Schema: it has no
top-level ``type: object`` / ``properties`` and invents keywords (``oneOf``
branches carrying ``target`` / ``operation`` / ``required`` / ``optional``,
``bounds``, ``alias_of``, ``backend_derived``, ``payload``, ``composes``). The
pinned CLI validates a tool's ``inputSchema`` as JSON Schema and SILENTLY DROPS
non-conforming tools after connecting - the S20 "connected but not exposed"
root cause. This module translates each catalog schema into a valid JSON Schema
object at the bridge serving boundary.

Design posture: the ENGINE remains the execution-time authority (server-side
validation + human-approval gating). The normalized schema's job is to REGISTER
the tool (so the CLI keeps it) and GUIDE the model (field names, discriminators,
bounds as prose) - NOT to enforce the DSL's full semantics. The original catalog
schema is never mutated; normalization happens only at serving time.
"""

from __future__ import annotations

from typing import Any

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
    return [item for item in value if isinstance(item, str) and item not in exclude]


def normalize_tool_input_schema(
    raw: object, injected: frozenset[str] = frozenset()
) -> tuple[dict[str, Any], str]:
    """Translate one catalog ``input_schema`` to ``(json_schema, guidance)``.

    ``json_schema`` is always a valid JSON Schema object (``type: object``,
    ``properties``, ``additionalProperties: false``, and ``required`` when the
    intersection is non-empty). ``guidance`` is prose the caller appends to the
    tool description so the per-branch requirements, bounds, and dropped engine
    keywords still reach the model. A non-dict input yields a bare object schema.

    *injected* names the fields the dispatcher owns and injects run-scoped
    (session_id / changeset_id / expected_revision / approval_id for a proposal
    command). They are removed from properties, required, and the branch guidance
    so they never appear in the model's contract - the model must not, and cannot,
    supply them. Read tools pass an empty set, keeping their target ids
    model-owned.
    """
    if not isinstance(raw, dict):
        return {"type": "object"}, ""

    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    guidance_parts: list[str] = []
    # A tool/branch carrying an opaque ``payload`` type (or aliasing another
    # tool's input) whose fields the DSL does NOT enumerate cannot be a closed
    # schema: the engine flattens the payload at the top level
    # (``#[serde(tag=..., flatten)]``), so the model must be able to send those
    # fields. Leave such schemas open (no ``additionalProperties: false``); the
    # engine deserializes and validates the real shape.
    open_schema = False

    branches = raw.get("oneOf")
    if isinstance(branches, list) and branches:
        required_sets: list[set[str]] = []
        enum_values: dict[str, list[str]] = {}
        branch_notes: list[str] = []
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            b_required = _str_list(branch.get("required"), injected)
            b_optional = _str_list(branch.get("optional"), injected)
            for field in (*b_required, *b_optional):
                properties.setdefault(field, _permissive_field())
            required_sets.append(set(b_required))
            payload = branch.get("payload")
            alias_of = branch.get("alias_of")
            note_parts: list[str] = []
            if b_required:
                note_parts.append("requires " + ", ".join(b_required))
            if isinstance(payload, str):
                open_schema = True
                note_parts.append(f"sends payload {payload}")
            if isinstance(alias_of, str) and not (b_required or b_optional):
                # An alias with no enumerated fields is an opaque input shape.
                open_schema = True
                note_parts.append(f"input aliases {alias_of}")
            discriminator: tuple[str, str] | None = None
            for key in _DISCRIMINATOR_KEYS:
                value = branch.get(key)
                if isinstance(value, str):
                    values = enum_values.setdefault(key, [])
                    if value not in values:
                        values.append(value)
                    discriminator = (key, value)
                    break
            if discriminator is not None:
                key, value = discriminator
                detail = "; ".join(note_parts) if note_parts else "no fields"
                branch_notes.append(f"{key}={value!r} {detail}")
        for disc_key, values in enum_values.items():
            properties[disc_key] = {"type": "string", "enum": values}
        # Per-branch required sets differ, so the top-level guarantee is their
        # intersection (often empty); per-branch requirements ride the guidance.
        if required_sets:
            required = sorted(set.intersection(*required_sets))
        if branch_notes:
            guidance_parts.append("One of: " + "; ".join(branch_notes) + ".")
    else:
        b_required = _str_list(raw.get("required"), injected)
        b_optional = _str_list(raw.get("optional"), injected)
        for field in (*b_required, *b_optional):
            properties.setdefault(field, _permissive_field())
        required = sorted(b_required)
        # A top-level opaque payload (e.g. request_apply -> ApplyRequest) has no
        # enumerated fields, so the schema must stay open for the model to send it.
        if isinstance(raw.get("payload"), str):
            open_schema = True

    bounds = raw.get("bounds")
    if isinstance(bounds, dict) and bounds:
        guidance_parts.append(
            "Bounds: " + ", ".join(f"{k}={v}" for k, v in bounds.items()) + "."
        )

    unknown = {k: v for k, v in raw.items() if k not in _CONSUMED_KEYS}
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
