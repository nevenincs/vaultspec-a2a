"""Direct normalization tests for prompt-free ACP catalog discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from ..acp_catalog import (
    AcpCatalogProtocolError,
    _rpc_error,
    _unauthenticated_discovery,
    catalog_from_session_result,
)
from ..provider_catalog import (
    MAX_CONTROLS,
    MAX_OPTIONS,
    AuthenticationState,
    CatalogStatus,
    ControlKind,
    ProviderCatalogKey,
)

if TYPE_CHECKING:
    from .._json_contract import JsonObject

_KEY = ProviderCatalogKey("provider-under-test", "acp")


def test_config_options_normalize_models_and_native_controls() -> None:
    catalog = catalog_from_session_result(
        {
            "sessionId": "session-one",
            "configOptions": [
                {
                    "configId": "model",
                    "name": "Model",
                    "category": "model",
                    "type": "select",
                    "currentValue": "provider-model-a",
                    "options": [
                        {"value": "provider-model-a", "name": "Model A"},
                        {"value": "provider-model-b", "name": "Model B"},
                    ],
                },
                {
                    "configId": "thinking",
                    "name": "Thinking",
                    "category": "thought_level",
                    "type": "select",
                    "currentValue": "balanced",
                    "options": [
                        {"value": "balanced", "name": "Balanced"},
                        {"value": "extended", "name": "Extended"},
                    ],
                },
                {
                    "configId": "context",
                    "name": "Context",
                    "category": "model_config",
                    "type": "select",
                    "currentValue": "standard",
                    "options": [{"value": "standard", "name": "Standard"}],
                },
            ],
        },
        key=_KEY,
        checked_at=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert catalog.state.status is CatalogStatus.AVAILABLE
    assert [model.provider_value for model in catalog.models] == [
        "provider-model-a",
        "provider-model-b",
    ]
    assert [control.kind for control in catalog.native_controls] == [
        ControlKind.THOUGHT_LEVEL,
        ControlKind.MODEL_CONFIG,
    ]
    assert catalog.native_controls[0].options[0].provider_value == "balanced"
    assert catalog.native_controls[0].default_option_id is not None
    expected_control_ids = tuple(
        control.control_id for control in catalog.native_controls
    )
    assert all(
        model.native_control_ids == expected_control_ids for model in catalog.models
    )


def test_grouped_model_options_preserve_provider_order() -> None:
    catalog = catalog_from_session_result(
        {
            "configOptions": [
                {
                    "id": "models",
                    "category": "model",
                    "type": "select",
                    "options": [
                        {
                            "group": "First",
                            "options": [{"value": "first", "name": "First"}],
                        },
                        {
                            "group": "Second",
                            "options": [{"value": "second", "name": "Second"}],
                        },
                    ],
                }
            ]
        },
        key=_KEY,
    )
    assert [model.provider_value for model in catalog.models] == ["first", "second"]


def test_gemini_models_shape_normalizes_without_invented_options() -> None:
    catalog = catalog_from_session_result(
        {
            "models": {
                "currentModelId": "gemini-current",
                "availableModels": [
                    {"modelId": "gemini-current", "name": "Current"},
                    {"modelId": "gemini-other", "name": "Other"},
                ],
            }
        },
        key=_KEY,
    )
    assert [model.provider_value for model in catalog.models] == [
        "gemini-current",
        "gemini-other",
    ]
    assert catalog.native_controls == ()


def test_missing_enumeration_is_truthfully_unavailable() -> None:
    catalog = catalog_from_session_result({"sessionId": "session"}, key=_KEY)
    assert catalog.state.status is CatalogStatus.UNAVAILABLE
    assert catalog.models == ()
    assert "did not advertise" in (catalog.state.reason or "")


def test_malformed_or_duplicate_provider_values_fail_closed() -> None:
    with pytest.raises(AcpCatalogProtocolError, match="duplicate"):
        catalog_from_session_result(
            {
                "configOptions": [
                    {
                        "id": "model",
                        "category": "model",
                        "type": "select",
                        "options": [
                            {"value": "same", "name": "First"},
                            {"value": "same", "name": "Second"},
                        ],
                    }
                ]
            },
            key=_KEY,
        )
    with pytest.raises(AcpCatalogProtocolError, match="must be a list"):
        catalog_from_session_result({"configOptions": "invalid"}, key=_KEY)


def test_catalog_revision_is_stable_and_provider_value_sensitive() -> None:
    first = catalog_from_session_result(
        {"models": {"availableModels": [{"value": "provider-value-a", "name": "A"}]}},
        key=_KEY,
    )
    same = catalog_from_session_result(
        {"models": {"availableModels": [{"value": "provider-value-a", "name": "A"}]}},
        key=_KEY,
    )
    changed = catalog_from_session_result(
        {"models": {"availableModels": [{"value": "provider-value-b", "name": "B"}]}},
        key=_KEY,
    )
    assert first.state.revision == same.state.revision
    assert first.state.revision != changed.state.revision


def test_provider_error_text_is_not_retained() -> None:
    secret = "credential-value-that-must-not-escape"
    error = _rpc_error(
        "session/new", {"code": -32603, "message": f"provider failed: {secret}"}
    )
    assert secret not in str(error)
    assert str(error).endswith("ACP session/new failed with a provider error")


def test_authentication_required_is_a_truthful_unavailable_outcome() -> None:
    discovery = _unauthenticated_discovery(_KEY)
    assert discovery.authentication is AuthenticationState.UNAUTHENTICATED
    assert discovery.catalog.state.status is CatalogStatus.UNAVAILABLE
    assert discovery.catalog.models == ()
    assert discovery.catalog.state.reason == "provider session requires authentication"


def test_control_and_option_bounds_fail_as_protocol_errors() -> None:
    controls: list[JsonObject] = [
        {
            "id": f"control-{index}",
            "category": "thought_level",
            "type": "select",
            "options": [{"value": "one", "name": "One"}],
        }
        for index in range(MAX_CONTROLS + 1)
    ]
    with pytest.raises(
        AcpCatalogProtocolError, match=f"more than {MAX_CONTROLS} controls"
    ):
        catalog_from_session_result(
            cast("JsonObject", {"configOptions": controls}), key=_KEY
        )

    options: list[JsonObject] = [
        {"value": f"choice-{index}", "name": f"Choice {index}"}
        for index in range(MAX_OPTIONS + 1)
    ]
    with pytest.raises(AcpCatalogProtocolError, match=f"exceeds {MAX_OPTIONS} items"):
        catalog_from_session_result(
            cast(
                "JsonObject",
                {
                    "configOptions": [
                        {
                            "id": "thought",
                            "category": "thought_level",
                            "type": "select",
                            "options": options,
                        }
                    ]
                },
            ),
            key=_KEY,
        )
