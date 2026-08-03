"""One served catalog selection, read from the gateway under test.

Run start refuses a body without a `selection` and revalidates the reference it
receives against the catalog served FOR THAT WORKSPACE. A hand-written reference
is therefore refused even when its shape is perfect: it has to name a lane the
gateway actually reports as selectable, at that lane's current revision.

Shared across the desktop suites because each of them starts its own real
gateway, and the first read on a gateway probes every provider lane. Caching per
gateway and workspace keeps that cost paid once rather than once per request.
"""

from __future__ import annotations

from typing import Any

import httpx

__all__ = ["catalog_selection"]

_CACHE: dict[str, dict[str, Any]] = {}


def catalog_selection(base: str, auth: str, workspace_root: str) -> dict[str, Any]:
    """Return one served selection for *workspace_root* on the gateway at *base*."""
    key = f"{base}|{workspace_root}"
    cached = _CACHE.get(key)
    if cached is None:
        with httpx.Client(base_url=base, timeout=180.0) as client:
            response = client.get(
                "/v1/provider-catalog",
                headers={"Authorization": auth},
                params={"workspace_root": workspace_root},
            )
        assert response.status_code == 200, response.text
        record = next(
            item
            for item in response.json()["providers"]
            if item["health"]["selectable"] and item["catalog"]["models"]
        )
        catalog = record["catalog"]
        cached = {
            "schema_version": 1,
            "provider_id": record["provider_id"],
            "execution_mode": record["execution_mode"],
            "catalog_revision": catalog["state"]["revision"],
            "entry_id": catalog["models"][0]["entry_id"],
            "controls": {},
        }
        _CACHE[key] = cached
    # Copied per call so a caller mutating its body cannot reach the cache and
    # silently change what every later request in the session selects.
    return dict(cached)
