"""Every discovery lane refuses at the model and control counts the model declares.

``ProviderCatalog`` declares how many models one provider lane may advertise and
how many provider-native controls may accompany them. Four discovery lanes each
declared a private copy of the model count and three a private copy of the
control count - seven numbers for two facts. The copies agreed, which is exactly
why nothing noticed: a restated bound and a consumed one are indistinguishable
while they hold the same value, and they hold it only until someone edits one.

The lane checks themselves are kept, because they do something the model cannot.
Each refuses EARLY, in its own protocol dialect, before the domain object is
built - so a provider advertising an absurd catalog produces a lane-specific
discovery refusal rather than a bare ``ValueError`` surfacing from a dataclass
constructor two layers down. That is an error mapping, and each lane is entitled
to its own. What no lane was entitled to is its own NUMBER: a lane bound above
the model builds a catalog the model then rejects, and a lane bound below it
refuses catalogs the model accepts, for a reason stated nowhere.

So agreement is measured behaviourally rather than asserted about the source.
Each lane is driven through its real normalization entry point with real
payloads: exactly the cap is ADMITTED, one more is REFUSED. The admitted case is
asserted alongside the refused one because a lane that rejected everything would
also produce the refusals, and because two lanes drop their controls entirely
when a payload advertises no models - a refusal-only test there would assert
nothing about the cap.

Two lanes do arithmetic on the shared bound, and both cases are legitimate and
covered here rather than normalized away. ACP carries its model selector in the
same wire list as its controls, so its early bound is one MORE than the control
cap; the admitted control case advertises the full complement of controls plus a
model selector, which is exactly the payload a lane bound at the flat cap would
wrongly refuse. Codex accumulates models across pages, so each page is bounded by
what the cap leaves rather than by the whole cap; its refused model case puts the
overflowing model on a SECOND page, where only that accumulation can catch it.

The counts are read from the authority, never restated here, so this follows the
bounds wherever they move - and a lane that reintroduces a private copy fails
here as soon as the two disagree, rather than on the day a provider ships a
catalog between the two values.

The OpenAI-compatible lane appears only among the model lanes: it normalizes
opaque model identifiers and advertises no native controls at all, so it has no
control count to agree about.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ..acp_catalog import AcpCatalogProtocolError, catalog_from_session_result
from ..codex_catalog import CodexCatalogProtocolError, catalog_from_app_server
from ..kimi_catalog import KimiCatalogProtocolError, catalog_from_provider_list
from ..openai_catalog import OpenAICompatibleCatalogError, catalog_from_model_list
from ..provider_catalog import (
    MAX_CONTROLS,
    MAX_MODELS,
    ProviderCatalog,
    ProviderCatalogKey,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .._json_contract import JsonObject, JsonValue

_KEY = ProviderCatalogKey("lane", "cli")

_CAPABILITIES: JsonObject = {
    "webSearch": False,
    "imageGeneration": False,
    "namespaceTools": False,
}


def _acp_models(model_count: int) -> ProviderCatalog:
    """Normalize an ACP session advertising *model_count* model choices."""
    return catalog_from_session_result(
        cast(
            "JsonObject",
            {
                "sessionId": "session-one",
                "configOptions": [
                    {
                        "configId": "model",
                        "category": "model",
                        "type": "select",
                        "options": [
                            {"value": f"wire-{index}", "name": f"Wire {index}"}
                            for index in range(model_count)
                        ],
                    }
                ],
            },
        ),
        key=_KEY,
    )


def _acp_controls(control_count: int) -> ProviderCatalog:
    """Normalize an ACP session advertising *control_count* native selectors.

    The session also advertises its one model selector, both because a session
    without models yields no controls at all and because the model selector
    shares the wire list the controls are bounded by.
    """
    config_options: list[JsonObject] = [
        {
            "configId": "model",
            "category": "model",
            "type": "select",
            "options": [{"value": "wire-model", "name": "Wire model"}],
        }
    ]
    config_options.extend(
        {
            "configId": f"thought-{index}",
            "category": "thought_level",
            "type": "select",
            "options": [{"value": f"effort-{index}", "name": f"Effort {index}"}],
        }
        for index in range(control_count)
    )
    return catalog_from_session_result(
        cast(
            "JsonObject", {"sessionId": "session-one", "configOptions": config_options}
        ),
        key=_KEY,
    )


def _codex_model(value: str, *, efforts: tuple[str, ...] = ()) -> JsonObject:
    """Build one app-server model row, control-bearing only when given efforts.

    ``supportedReasoningEfforts`` is required by the lane even when empty, so a
    control-free row carries the empty list rather than omitting the field - an
    omission is refused for a reason that has nothing to do with any count.
    """
    row: JsonObject = {
        "id": f"picker-{value}",
        "model": value,
        "displayName": value,
        "hidden": False,
        "isDefault": False,
        "supportedReasoningEfforts": [
            {"reasoningEffort": effort, "description": f"{effort} reasoning"}
            for effort in efforts
        ],
    }
    if efforts:
        row["defaultReasoningEffort"] = efforts[0]
    return row


def _codex_models(model_count: int) -> ProviderCatalog:
    """Normalize *model_count* control-free Codex models split across two pages.

    The split is what exercises the per-page remainder: the last model arrives on
    a page of its own, so only the accumulated count can refuse it.
    """
    rows: list[JsonValue] = [
        _codex_model(f"wire-{index}") for index in range(model_count)
    ]
    first: JsonObject = {"data": rows[:-1], "nextCursor": "page-two"}
    last: JsonObject = {"data": rows[-1:], "nextCursor": None}
    return catalog_from_app_server((first, last), _CAPABILITIES, key=_KEY)


def _codex_controls(control_count: int) -> ProviderCatalog:
    """Normalize *control_count* Codex models each carrying one native control."""
    rows: list[JsonValue] = [
        _codex_model(f"wire-{index}", efforts=(f"effort-{index}",))
        for index in range(control_count)
    ]
    page: JsonObject = {"data": rows, "nextCursor": None}
    return catalog_from_app_server((page,), _CAPABILITIES, key=_KEY)


def _kimi_catalog(model_count: int, *, with_efforts: bool) -> ProviderCatalog:
    """Normalize a Kimi provider list of *model_count* aliases."""
    model: JsonObject = {
        "provider": "configured-provider",
        "model": "wire-model",
        "maxContextSize": 131_072,
    }
    if with_efforts:
        model["supportEfforts"] = ["brief", "deep"]
        model["defaultEffort"] = "brief"
    return catalog_from_provider_list(
        cast(
            "JsonObject",
            {
                "providers": {
                    "configured-provider": {
                        "type": "kimi",
                        "apiKey": "credential-value-that-must-not-escape",
                    }
                },
                "models": {
                    f"alias-{index}": {**model, "model": f"wire-{index}"}
                    for index in range(model_count)
                },
            },
        ),
        key=_KEY,
    )


def _kimi_models(model_count: int) -> ProviderCatalog:
    """Normalize *model_count* control-free Kimi aliases."""
    return _kimi_catalog(model_count, with_efforts=False)


def _kimi_controls(control_count: int) -> ProviderCatalog:
    """Normalize *control_count* Kimi aliases each carrying a thinking control."""
    return _kimi_catalog(control_count, with_efforts=True)


def _openai_models(model_count: int) -> ProviderCatalog:
    """Normalize an OpenAI-compatible model list of *model_count* identifiers."""
    return catalog_from_model_list(
        cast(
            "JsonObject",
            {
                "object": "list",
                "data": [
                    {
                        "id": f"provider/model-{index}",
                        "object": "model",
                        "created": 1_700_000_000,
                        "owned_by": "provider-owner-that-is-not-served",
                    }
                    for index in range(model_count)
                ],
            },
        ),
        key=_KEY,
    )


_MODEL_LANES: tuple[
    tuple[str, Callable[[int], ProviderCatalog], type[Exception]], ...
] = (
    ("acp", _acp_models, AcpCatalogProtocolError),
    ("codex", _codex_models, CodexCatalogProtocolError),
    ("kimi", _kimi_models, KimiCatalogProtocolError),
    ("openai", _openai_models, OpenAICompatibleCatalogError),
)

_CONTROL_LANES: tuple[
    tuple[str, Callable[[int], ProviderCatalog], type[Exception]], ...
] = (
    ("acp", _acp_controls, AcpCatalogProtocolError),
    ("codex", _codex_controls, CodexCatalogProtocolError),
    ("kimi", _kimi_controls, KimiCatalogProtocolError),
)


@pytest.mark.parametrize(("lane", "normalize", "refusal"), _MODEL_LANES)
def test_a_lane_admits_a_catalog_at_exactly_the_declared_model_cap(
    lane: str,
    normalize: Callable[[int], ProviderCatalog],
    refusal: type[Exception],
) -> None:
    """A catalog carrying the model cap exactly must survive lane and model."""
    del refusal
    catalog = normalize(MAX_MODELS)

    assert len(catalog.models) == MAX_MODELS, (
        f"{lane} admitted the catalog but kept {len(catalog.models)} of "
        f"{MAX_MODELS} models; a lane that silently truncates serves a catalog "
        "the provider did not advertise"
    )


@pytest.mark.parametrize(("lane", "normalize", "refusal"), _MODEL_LANES)
def test_a_lane_refuses_one_model_beyond_the_declared_cap(
    lane: str,
    normalize: Callable[[int], ProviderCatalog],
    refusal: type[Exception],
) -> None:
    """One model past the cap must be refused in the lane's own dialect.

    The refusal type is asserted per lane, which is the property that keeps the
    lane checks worth having: the bound is shared, the error mapping is not.
    """
    del lane
    with pytest.raises(refusal):
        normalize(MAX_MODELS + 1)


@pytest.mark.parametrize(("lane", "normalize", "refusal"), _CONTROL_LANES)
def test_a_lane_admits_a_catalog_at_exactly_the_declared_control_cap(
    lane: str,
    normalize: Callable[[int], ProviderCatalog],
    refusal: type[Exception],
) -> None:
    """A catalog carrying the control cap exactly must survive lane and model."""
    del refusal
    catalog = normalize(MAX_CONTROLS)

    assert catalog.models, (
        f"{lane} produced no models, so its controls were dropped and this "
        "asserts nothing about the control cap"
    )
    assert len(catalog.native_controls) == MAX_CONTROLS, (
        f"{lane} admitted the catalog but kept {len(catalog.native_controls)} "
        f"of {MAX_CONTROLS} native controls"
    )


@pytest.mark.parametrize(("lane", "normalize", "refusal"), _CONTROL_LANES)
def test_a_lane_refuses_one_control_beyond_the_declared_cap(
    lane: str,
    normalize: Callable[[int], ProviderCatalog],
    refusal: type[Exception],
) -> None:
    """One native control past the cap must be refused in the lane's dialect."""
    del lane
    with pytest.raises(refusal):
        normalize(MAX_CONTROLS + 1)
