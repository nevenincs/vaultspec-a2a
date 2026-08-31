"""One served catalog selection, read from the gateway under test.

Run start refuses a body without a `selection` and revalidates the reference it
receives against the catalog served FOR THAT WORKSPACE. A hand-written reference
is therefore refused even when its shape is perfect: it has to name a lane the
gateway actually reports as selectable, at that lane's current revision.

Shared across the desktop suites because each of them starts its own real
gateway, and the first read on a gateway probes every provider lane. Caching per
gateway and workspace keeps that cost paid once rather than once per request.

The lane choice is delegated to :func:`in_process_selection` rather than made
here: every desktop suite runs the ``mock-success-single`` preset, pinned to the
in-process mock lane, and a "take whatever is selectable" derivation would pick a
real, billable provider on any developer box that happens to hold a live session
for one - silently substituting a lane none of these certifications asked for.
Every armed desktop gateway this module is pointed at must serve the in-process
lanes (``VAULTSPEC_SERVE_IN_PROCESS_LANES=true``); an unarmed gateway fails here
by naming the missing declaration rather than by picking something else.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..testing.catalog_selection import in_process_selection

__all__ = ["catalog_selection"]

_CACHE: dict[str, dict[str, Any]] = {}


def catalog_selection(base: str, auth: str, workspace_root: str) -> dict[str, Any]:
    """Return one served in-process selection for *workspace_root* at *base*."""
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
        cached = in_process_selection(response.json(), prefer_provider_id="mock")
        _CACHE[key] = cached
    # Copied per call so a caller mutating its body cannot reach the cache and
    # silently change what every later request in the session selects.
    return dict(cached)
