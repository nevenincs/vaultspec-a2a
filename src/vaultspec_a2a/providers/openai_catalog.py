"""Prompt-free OpenAI-compatible model discovery over a caller-bound API lane.

The adapter issues exactly one authenticated ``GET /models`` request. It does
not create a completion and deliberately retains only provider-issued model
identifiers: the compatible contract advertises neither product tiers nor
provider-native controls or capabilities.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Final

import httpx
from pydantic import TypeAdapter, ValidationError

from ._catalog_fields import CatalogFieldReader, local_id, model_list_revision
from ._json_contract import JsonObject
from .provider_catalog import (
    MAX_MODELS,
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    ModelCatalogEntry,
    ProviderCatalog,
    ProviderCatalogKey,
)

__all__ = [
    "OpenAICompatibleCatalogDiscovery",
    "OpenAICompatibleCatalogError",
    "catalog_from_model_list",
    "discover_openai_compatible_catalog",
]

_MAX_RESPONSE_BYTES: Final = 1_048_576
_MAX_API_KEY_LENGTH: Final = 4_096
_CATALOG_TTL: Final = timedelta(minutes=5)
_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)
_LINK_RELATION: Final = re.compile(
    r"(?:^|;)\s*rel\s*=\s*(?:\"([^\"]*)\"|([^;,\s]+))",
    re.I,
)
_NEXT_FIELDS: Final = ("next", "next_page", "next_cursor")


class OpenAICompatibleCatalogError(RuntimeError):
    """The OpenAI-compatible model-list contract was unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class OpenAICompatibleCatalogDiscovery:
    """One bounded model-list result and its authentication evidence."""

    catalog: ProviderCatalog
    authentication: AuthenticationState


def _protocol_error(message: str) -> OpenAICompatibleCatalogError:
    """Raise this lane's own dialect of a catalog contract refusal."""
    return OpenAICompatibleCatalogError(f"OpenAI-compatible {message}")


_FIELDS: Final = CatalogFieldReader(_protocol_error)


def _models_url(base_url: str) -> str:
    if not base_url or base_url != base_url.strip():
        raise ValueError("base_url must be a normalized non-blank string")
    try:
        parsed = httpx.URL(base_url)
    except httpx.InvalidURL:
        raise ValueError("base_url must be an absolute HTTP(S) URL") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.host
        or parsed.userinfo
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "base_url must be an absolute HTTP(S) URL without credentials, query, "
            "or fragment"
        )
    if parsed.scheme == "http" and parsed.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("base_url must use HTTPS unless it is loopback")
    path = parsed.path.rstrip("/")
    return str(parsed.copy_with(path=f"{path}/models" if path else "/models"))


def _api_key(value: str) -> str:
    if len(value) > _MAX_API_KEY_LENGTH or any(
        not 0x21 <= ord(character) <= 0x7E for character in value
    ):
        raise ValueError("api_key must be a bounded normalized value")
    return value


def _entry_id(key: ProviderCatalogKey, provider_value: str) -> str:
    return local_id(f"{key.provider_id}:{key.execution_mode}:model", provider_value)


def _unavailable_catalog(
    key: ProviderCatalogKey,
    *,
    reason: str,
    checked_at: datetime | None = None,
) -> ProviderCatalog:
    return ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.UNAVAILABLE,
            checked_at=(checked_at or datetime.now(UTC)).astimezone(UTC),
            reason=reason,
        ),
        models=(),
    )


def _has_next_page(link_header: str | None) -> bool:
    if link_header is None:
        return False
    return any(
        "next" in (match.group(1) or match.group(2) or "").casefold().split()
        for match in _LINK_RELATION.finditer(link_header)
    )


def catalog_from_model_list(
    result: JsonObject,
    *,
    key: ProviderCatalogKey,
    checked_at: datetime | None = None,
) -> ProviderCatalog:
    """Normalize only opaque model IDs from one complete model-list response."""
    has_more = result.get("has_more")
    if has_more is not None and not isinstance(has_more, bool):
        raise OpenAICompatibleCatalogError(
            "OpenAI-compatible model-list has_more must be a boolean when present"
        )
    if has_more:
        raise OpenAICompatibleCatalogError(
            "OpenAI-compatible model-list pagination cannot be exhausted"
        )
    if any(result.get(field) is not None for field in _NEXT_FIELDS):
        raise OpenAICompatibleCatalogError(
            "OpenAI-compatible model-list pagination cannot be exhausted"
        )
    if result.get("object") != "list":
        raise OpenAICompatibleCatalogError(
            "OpenAI-compatible model-list has an invalid object type"
        )
    raw_models = result.get("data")
    if not isinstance(raw_models, list):
        raise OpenAICompatibleCatalogError(
            "OpenAI-compatible model-list data must be a list"
        )
    if len(raw_models) > MAX_MODELS:
        raise OpenAICompatibleCatalogError(
            f"OpenAI-compatible model-list exceeds {MAX_MODELS} models"
        )
    model_values: set[str] = set()
    for index, raw_model in enumerate(raw_models):
        if not isinstance(raw_model, dict):
            raise OpenAICompatibleCatalogError(
                f"OpenAI-compatible model-list data[{index}] must be an object"
            )
        if raw_model.get("object") != "model":
            raise OpenAICompatibleCatalogError(
                f"OpenAI-compatible model-list data[{index}] has an invalid object type"
            )
        created = raw_model.get("created")
        if not isinstance(created, int) or isinstance(created, bool) or created < 0:
            raise OpenAICompatibleCatalogError(
                f"OpenAI-compatible model-list data[{index}].created must be "
                "a non-negative integer"
            )
        _FIELDS.required_text(
            raw_model.get("owned_by"), field=f"data[{index}].owned_by"
        )
        model_value = _FIELDS.required_text(
            raw_model.get("id"), field=f"data[{index}].id"
        )
        if model_value in model_values:
            raise OpenAICompatibleCatalogError(
                "OpenAI-compatible model-list contains duplicate identifiers"
            )
        model_values.add(model_value)
    now = (checked_at or datetime.now(UTC)).astimezone(UTC)
    if not model_values:
        return _unavailable_catalog(
            key,
            checked_at=now,
            reason="provider returned no models",
        )
    models = tuple(
        ModelCatalogEntry(
            entry_id=_entry_id(key, model_value),
            provider_value=model_value,
            display_name=model_value[:256],
        )
        for model_value in sorted(model_values)
    )
    return ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=now,
            revision=model_list_revision(key, models),
            expires_at=now + _CATALOG_TTL,
        ),
        models=models,
    )


async def discover_openai_compatible_catalog(
    *,
    base_url: str,
    api_key: str | None,
    key: ProviderCatalogKey,
    timeout: float = 30.0,
) -> OpenAICompatibleCatalogDiscovery:
    """Get the complete model list without following redirects or sending a prompt."""
    models_url = _models_url(base_url)
    if not isinstance(api_key, str) or not api_key or api_key != api_key.strip():
        return OpenAICompatibleCatalogDiscovery(
            catalog=_unavailable_catalog(
                key,
                reason="provider model-list requires an API key",
            ),
            authentication=AuthenticationState.UNAUTHENTICATED,
        )
    bearer = _api_key(api_key)
    if isinstance(timeout, bool) or not isfinite(float(timeout)) or timeout <= 0:
        raise ValueError("timeout must be positive")
    try:
        async with (
            asyncio.timeout(float(timeout)),
            httpx.AsyncClient(
                follow_redirects=False,
                timeout=timeout,
                trust_env=False,
            ) as client,
            client.stream(
                "GET",
                models_url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {bearer}",
                },
            ) as response,
        ):
            if response.status_code == 401:
                return OpenAICompatibleCatalogDiscovery(
                    catalog=_unavailable_catalog(
                        key,
                        reason="provider model-list authentication failed",
                    ),
                    authentication=AuthenticationState.UNAUTHENTICATED,
                )
            if response.status_code == 403:
                return OpenAICompatibleCatalogDiscovery(
                    catalog=_unavailable_catalog(
                        key,
                        reason="provider model-list request was forbidden",
                    ),
                    authentication=AuthenticationState.UNKNOWN,
                )
            if response.status_code != 200:
                raise OpenAICompatibleCatalogError(
                    "OpenAI-compatible model-list request failed"
                )
            if _has_next_page(response.headers.get("Link")):
                raise OpenAICompatibleCatalogError(
                    "OpenAI-compatible model-list pagination cannot be exhausted"
                )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                    raise OpenAICompatibleCatalogError(
                        "OpenAI-compatible model-list response exceeds one MiB"
                    )
                body.extend(chunk)
    except (TimeoutError, httpx.TimeoutException):
        raise OpenAICompatibleCatalogError(
            "OpenAI-compatible model-list request timed out"
        ) from None
    except (UnicodeError, httpx.HTTPError):
        raise OpenAICompatibleCatalogError(
            "OpenAI-compatible model-list request failed"
        ) from None
    try:
        result = _JSON_OBJECT.validate_json(bytes(body))
    except (ValidationError, UnicodeDecodeError):
        raise OpenAICompatibleCatalogError(
            "OpenAI-compatible model-list returned malformed JSON"
        ) from None
    return OpenAICompatibleCatalogDiscovery(
        catalog=catalog_from_model_list(result, key=key),
        authentication=AuthenticationState.AUTHENTICATED,
    )
