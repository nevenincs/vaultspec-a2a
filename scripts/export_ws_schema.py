"""Export WebSocket event and command JSON Schemas from Pydantic models.

These schemas are NOT in the OpenAPI spec (FastAPI doesn't expose WS schemas).
They serve as the source of truth for TypeScript type generation.

Usage: uv run python scripts/export_ws_schema.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"


def main() -> None:
    try:
        from pydantic import TypeAdapter

        from vaultspec_a2a.api.schemas.commands import ClientMessage
        from vaultspec_a2a.api.schemas.events import ServerEvent
    except ImportError as exc:
        print(f"Failed to import schemas: {exc}", file=sys.stderr)
        print("Ensure dependencies are installed: uv sync", file=sys.stderr)
        return 1

    SCHEMAS_DIR.mkdir(exist_ok=True)

    server_schema = TypeAdapter(ServerEvent).json_schema()
    client_schema = TypeAdapter(ClientMessage).json_schema()

    server_out = SCHEMAS_DIR / "ws-server-events.json"
    client_out = SCHEMAS_DIR / "ws-client-messages.json"

    for path, schema in [(server_out, server_schema), (client_out, client_schema)]:
        path.write_text(
            json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        )

    sv = len(server_schema.get("oneOf", []))
    sd = len(server_schema.get("$defs", {}))
    cv = len(client_schema.get("oneOf", []))

    print(f"ServerEvent: {sv} variants, {sd} $defs -> {server_out}")
    print(f"ClientMessage: {cv} variants -> {client_out}")


if __name__ == "__main__":
    sys.exit(main() or 0)
