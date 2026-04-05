"""Export the FastAPI OpenAPI spec to openapi.json without starting the server.

Usage: uv run python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    from vaultspec_a2a.api.app import create_app

    app = create_app()
    spec = app.openapi()

    out = ROOT / "openapi.json"
    out.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")

    schema_count = len(spec.get("components", {}).get("schemas", {}))
    print(f"Exported {schema_count} schemas to {out}")


if __name__ == "__main__":
    sys.exit(main() or 0)
