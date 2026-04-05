"""Generate TypeScript types from Pydantic WebSocket JSON Schemas.

Reads the JSON Schema files exported by export_ws_schema.py and emits
TypeScript interfaces with literal discriminators. Handles the specific
patterns Pydantic produces: $ref/$defs, const, enum, anyOf nullable,
oneOf discriminated unions.

Usage: uv run python scripts/generate_ws_types.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
OUT = ROOT / "src" / "ui" / "src" / "app" / "data" / "ws-types.ts"

# JSON Schema type -> TypeScript type
PRIMITIVE_MAP: dict[str, str] = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
}


def ref_name(ref: str) -> str:
    """Extract the type name from a $ref string."""
    return ref.rsplit("/", 1)[-1]


def resolve_type(prop: dict, defs: dict) -> str:
    """Convert a JSON Schema property to a TypeScript type string."""
    # $ref -> named type
    if "$ref" in prop:
        return ref_name(prop["$ref"])

    # const -> literal
    if "const" in prop:
        v = prop["const"]
        if isinstance(v, str):
            return f'"{v}"'
        return str(v)

    # enum -> union of literals
    if "enum" in prop:
        return " | ".join(f'"{v}"' for v in prop["enum"])

    # anyOf -> nullable pattern or union
    if "anyOf" in prop:
        variants = prop["anyOf"]
        null_variants = [v for v in variants if v.get("type") == "null"]
        non_null = [v for v in variants if v.get("type") != "null"]

        if null_variants and len(non_null) == 1:
            inner = resolve_type(non_null[0], defs)
            return f"{inner} | null"

        if null_variants and len(non_null) > 1:
            types = [resolve_type(v, defs) for v in non_null]
            return " | ".join(types) + " | null"

        return " | ".join(resolve_type(v, defs) for v in variants)

    # oneOf -> discriminated union
    if "oneOf" in prop:
        types = [resolve_type(v, defs) for v in prop["oneOf"]]
        return " | ".join(types)

    # array
    if prop.get("type") == "array":
        items = prop.get("items", {})
        if "oneOf" in items:
            inner = " | ".join(resolve_type(v, defs) for v in items["oneOf"])
            return f"({inner})[]"
        inner = resolve_type(items, defs)
        return f"{inner}[]"

    # object with additionalProperties -> Record
    if prop.get("type") == "object":
        if prop.get("additionalProperties") is True:
            return "Record<string, unknown>"
        if "properties" in prop:
            # Inline object — shouldn't happen for our schemas
            return "Record<string, unknown>"
        return "Record<string, unknown>"

    # primitive
    if "type" in prop:
        return PRIMITIVE_MAP.get(prop["type"], "unknown")

    return "unknown"


def emit_interface(name: str, defn: dict, defs: dict) -> str:
    """Emit a TypeScript interface from a JSON Schema object definition."""
    if defn.get("type") != "object" or "properties" not in defn:
        return ""

    props = defn["properties"]
    required_set = set(defn.get("required", []))
    lines: list[str] = []

    desc = defn.get("description", "")
    if desc:
        first_line = desc.split("\n")[0].strip()
        lines.append(f"/** {first_line} */")

    lines.append(f"export interface {name} {{")

    for pname, pschema in props.items():
        is_required = pname in required_set
        ts_type = resolve_type(pschema, defs)

        # Fields with const are always present (discriminator)
        has_const = "const" in pschema

        if is_required or has_const:
            lines.append(f"  {pname}: {ts_type};")
        else:
            lines.append(f"  {pname}?: {ts_type};")

    lines.append("}")
    return "\n".join(lines)


def emit_enum(name: str, defn: dict) -> str:
    """Emit a TypeScript string literal union from a JSON Schema enum."""
    values = defn.get("enum", [])
    if not values:
        return ""

    desc = defn.get("description", "")
    lines: list[str] = []
    if desc:
        first_line = desc.split("\n")[0].strip()
        lines.append(f"/** {first_line} */")

    union = " | ".join(f'"{v}"' for v in values)
    lines.append(f"export type {name} = {union};")
    return "\n".join(lines)


def emit_union(name: str, schema: dict) -> str:
    """Emit a top-level discriminated union type."""
    one_of = schema.get("oneOf", [])
    if not one_of:
        return ""

    disc = schema.get("discriminator", {})
    prop_name = disc.get("propertyName", "type")

    types = [ref_name(v["$ref"]) for v in one_of if "$ref" in v]
    lines = [f'/** Discriminated union on "{prop_name}" field. */']
    lines.append(f"export type {name} =")
    for i, t in enumerate(types):
        sep = ";" if i == len(types) - 1 else ""
        lines.append(f"  | {t}{sep}")
    return "\n".join(lines)


def generate(schema: dict, union_name: str) -> str:
    """Generate TypeScript from a full JSON Schema with $defs and oneOf."""
    defs = schema.get("$defs", {})
    blocks: list[str] = []

    # Emit enums first (they're referenced by interfaces)
    for name, defn in sorted(defs.items()):
        if "enum" in defn and defn.get("type") == "string":
            blocks.append(emit_enum(name, defn))

    # Emit interfaces
    for name, defn in sorted(defs.items()):
        if defn.get("type") == "object" and "properties" in defn:
            blocks.append(emit_interface(name, defn, defs))

    # Emit the top-level union
    blocks.append(emit_union(union_name, schema))

    return "\n\n".join(b for b in blocks if b)


def main() -> None:
    server_schema = json.loads((SCHEMAS_DIR / "ws-server-events.json").read_text())
    client_schema = json.loads((SCHEMAS_DIR / "ws-client-messages.json").read_text())

    header = dedent("""\
        /**
         * WebSocket protocol types — auto-generated from Pydantic models.
         *
         * DO NOT EDIT MANUALLY. Regenerate with:
         *   uv run python scripts/export_ws_schema.py
         *   uv run python scripts/generate_ws_types.py
         *
         * Source: TypeAdapter(ServerEvent).json_schema() and
         *         TypeAdapter(ClientMessage).json_schema()
         */
    """)

    server_ts = generate(server_schema, "ServerEvent")
    client_ts = generate(client_schema, "ClientMessage")

    output = "\n".join(
        [
            header,
            "// " + "=" * 70,
            "// Server-to-client events",
            "// " + "=" * 70,
            "",
            server_ts,
            "",
            "// " + "=" * 70,
            "// Client-to-server commands",
            "// " + "=" * 70,
            "",
            client_ts,
            "",
        ]
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(output)
    print(f"Generated {OUT}")


if __name__ == "__main__":
    sys.exit(main() or 0)
