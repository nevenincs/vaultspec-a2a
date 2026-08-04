"""Every discovery lane refuses at the option count the domain model declares.

``NativeControl`` caps how many options one provider-native selector may carry,
and each discovery lane bounds the wire collection that becomes those options.
Three lanes each declared their own private copy of that number. The copies
agreed, which is precisely why nothing noticed: a restated bound and a consumed
one are indistinguishable while they hold the same value, and they hold it only
until someone edits one of them.

The lanes are not redundant with the model, and folding their checks away would
lose something real. Each refuses EARLY, in its own protocol dialect, before the
domain object is built - so a provider advertising an absurd control produces a
lane-specific discovery refusal rather than a bare ``ValueError`` surfacing from
a dataclass constructor. That is an error mapping, and each lane is entitled to
its own. What no lane was entitled to is its own NUMBER: the model is the
authority on how many options a control may hold, and a lane bound above it
would build a control the model then rejects, while a lane bound below it would
refuse catalogs the model accepts, for a reason stated nowhere.

So this measures agreement behaviourally rather than asserting that the source
says something. Each lane is driven through its real normalization entry point
with real payloads: exactly the cap is ACCEPTED, one more is REFUSED. The
accepted case is asserted alongside the refused one because a lane that rejected
everything would also produce the refusals.

The count is read from the authority, never restated here, so this test follows
the bound wherever it moves - and a lane that reintroduces a private copy fails
here as soon as the two disagree, rather than on the day a provider ships a
catalog between the two values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ..acp_catalog import AcpCatalogProtocolError, catalog_from_session_result
from ..codex_catalog import CodexCatalogProtocolError, catalog_from_app_server
from ..kimi_catalog import KimiCatalogProtocolError, catalog_from_provider_list
from ..provider_catalog import MAX_OPTIONS, ProviderCatalog, ProviderCatalogKey

if TYPE_CHECKING:
    from collections.abc import Callable

    from .._json_contract import JsonObject

_KEY = ProviderCatalogKey("lane", "cli")


def _acp_catalog(option_count: int) -> ProviderCatalog:
    """Normalize an ACP session advertising *option_count* select choices."""
    options = [
        {"value": f"choice-{index}", "name": f"Choice {index}"}
        for index in range(option_count)
    ]
    return catalog_from_session_result(
        cast(
            "JsonObject",
            {
                "sessionId": "session-one",
                "configOptions": [
                    # A session advertising no models yields no controls at all,
                    # so the admitted case needs one to be about the cap.
                    {
                        "configId": "model",
                        "category": "model",
                        "type": "select",
                        "options": [{"value": "wire-model", "name": "Wire model"}],
                    },
                    {
                        "configId": "thought",
                        "category": "thought_level",
                        "type": "select",
                        "options": options,
                    },
                ],
            },
        ),
        key=_KEY,
    )


def _codex_catalog(option_count: int) -> ProviderCatalog:
    """Normalize a Codex model page advertising *option_count* reasoning efforts."""
    efforts = [f"effort-{index}" for index in range(option_count)]
    model: JsonObject = {
        "id": "picker-model",
        "model": "wire-model",
        "displayName": "Wire model",
        "hidden": False,
        "isDefault": False,
        "defaultReasoningEffort": efforts[0],
        "supportedReasoningEfforts": [
            {"reasoningEffort": effort, "description": f"{effort} reasoning"}
            for effort in efforts
        ],
    }
    return catalog_from_app_server(
        ({"data": [model], "nextCursor": None},),
        {"webSearch": False, "imageGeneration": False, "namespaceTools": False},
        key=_KEY,
    )


def _kimi_catalog(option_count: int) -> ProviderCatalog:
    """Normalize a Kimi provider list advertising *option_count* thinking efforts."""
    efforts = [f"effort-{index}" for index in range(option_count)]
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
                    "configured-alias": {
                        "provider": "configured-provider",
                        "model": "wire-model",
                        "maxContextSize": 131_072,
                        "supportEfforts": efforts,
                    }
                },
            },
        ),
        key=_KEY,
    )


_LANES: tuple[tuple[str, Callable[[int], ProviderCatalog], type[Exception]], ...] = (
    ("acp", _acp_catalog, AcpCatalogProtocolError),
    ("codex", _codex_catalog, CodexCatalogProtocolError),
    ("kimi", _kimi_catalog, KimiCatalogProtocolError),
)


@pytest.mark.parametrize(("lane", "normalize", "refusal"), _LANES)
def test_a_lane_admits_a_control_at_exactly_the_declared_cap(
    lane: str,
    normalize: Callable[[int], ProviderCatalog],
    refusal: type[Exception],
) -> None:
    """A control carrying the cap exactly must survive the lane and the model."""
    del refusal
    catalog = normalize(MAX_OPTIONS)

    controls = catalog.native_controls
    assert len(controls) == 1, f"{lane} produced {len(controls)} controls, expected one"
    assert len(controls[0].options) == MAX_OPTIONS, (
        f"{lane} admitted the catalog but kept "
        f"{len(controls[0].options)} of {MAX_OPTIONS} options; a lane that "
        "silently truncates advertises a control the provider did not offer"
    )


@pytest.mark.parametrize(("lane", "normalize", "refusal"), _LANES)
def test_a_lane_refuses_one_option_beyond_the_declared_cap(
    lane: str,
    normalize: Callable[[int], ProviderCatalog],
    refusal: type[Exception],
) -> None:
    """One option past the cap must be refused in the lane's own dialect.

    The refusal type is asserted per lane, which is the property that keeps the
    lane checks worth having: the bound is shared, the error mapping is not.
    """
    with pytest.raises(refusal):
        normalize(MAX_OPTIONS + 1)
