"""Every lane bounds display text and capabilities at what the model declares.

``ProviderCatalog``'s dataclasses declare how long a display name may be and how
many capabilities a model may carry. A shared field helper restated the display
length as a private constant, three lanes restated it again as a bare ``[:256]``
slice, and one lane restated the capability count as a bare ``64``. All of them
agreed, which is why nothing noticed - a restated bound and a consumed one are
indistinguishable while they hold the same value.

The posture differs from the count bounds and deliberately so, which is the part
worth stating: the model REFUSES an over-long display name, while every lane
TRUNCATES one. That split is right. A provider shipping a 300-character label, or
a lane composing a label out of parts that are each legal, must not cost the
whole catalog. Truncating is the lane's decision in the same way its error
dialect is. The NUMBER is still not the lane's: cutting SHORTER silently shortens
a name the model would have accepted, and cutting LONGER hands the model a value
it rejects - as a bare ``ValueError`` out of a dataclass constructor rather than
a discovery refusal.

Agreement at the same value was NOT sufficient here, and that is the reason this
file exists rather than a one-line substitution. The model requires a display
name that is bounded AND already normalized. A cut landing on a space satisfies
the first and breaks the second, so a provider whose label happened to have a
space at the cut point lost its entire catalog to a constructor error. Every lane
carried it, because every lane truncated the same way. The bound and the
normalization now travel together in one helper, and the case is asserted below
against each lane's real entry point.

The ADMITTED case is asserted alongside the bounded one throughout, because a
lane that truncated everything to nothing would also never exceed the cap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from .._catalog_fields import display_label, optional_description
from ..acp_catalog import catalog_from_session_result
from ..codex_catalog import catalog_from_app_server
from ..kimi_catalog import KimiCatalogProtocolError, catalog_from_provider_list
from ..openai_catalog import catalog_from_model_list
from ..provider_catalog import (
    MAX_CAPABILITIES,
    MAX_DISPLAY_LENGTH,
    MAX_TEXT_LENGTH,
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

# Spaces recur every five characters, so shifting a name by nought through four
# lands one of them exactly on the cut point whatever fixed prefix a lane adds.
_WORD = "word "
_PHASES = range(len(_WORD))


def _spaced_name(phase: int, *, length: int) -> str:
    """Build a normalized over-long name whose spaces sit at *phase*."""
    return ("x" * phase + _WORD * (2 * length // len(_WORD)))[:length].strip()


def _acp_catalog(display_name: str) -> ProviderCatalog:
    """Normalize an ACP session whose model option carries *display_name*."""
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
                        "options": [{"value": "wire-model", "name": display_name}],
                    }
                ],
            },
        ),
        key=_KEY,
    )


def _codex_catalog(display_name: str) -> ProviderCatalog:
    """Normalize a Codex model whose displayName is *display_name*.

    The model also advertises a reasoning effort, so the derived control label -
    the lane's own composition, not the provider's string - is covered too.
    """
    rows: list[JsonValue] = [
        {
            "id": "picker-model",
            "model": "wire-model",
            "displayName": display_name,
            "hidden": False,
            "isDefault": False,
            "defaultReasoningEffort": "brief",
            "supportedReasoningEfforts": [
                {"reasoningEffort": "brief", "description": "brief reasoning"}
            ],
        }
    ]
    page: JsonObject = {"data": rows, "nextCursor": None}
    return catalog_from_app_server((page,), _CAPABILITIES, key=_KEY)


def _kimi_catalog(display_name: str) -> ProviderCatalog:
    """Normalize a Kimi alias whose displayName is *display_name*.

    The alias advertises a thinking effort, so the lane's composed control label
    is covered alongside the provider's own string.
    """
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
                        "displayName": display_name,
                        "supportEfforts": ["brief", "deep"],
                        "defaultEffort": "brief",
                    }
                },
            },
        ),
        key=_KEY,
    )


def _openai_catalog(display_name: str) -> ProviderCatalog:
    """Normalize an OpenAI-compatible list whose model id is *display_name*.

    This lane has no separate display field: the opaque identifier IS the label,
    which is why it truncates one and keeps the other whole.
    """
    return catalog_from_model_list(
        cast(
            "JsonObject",
            {
                "object": "list",
                "data": [
                    {
                        "id": display_name,
                        "object": "model",
                        "created": 1_700_000_000,
                        "owned_by": "provider-owner-that-is-not-served",
                    }
                ],
            },
        ),
        key=_KEY,
    )


_DISPLAY_LANES: tuple[tuple[str, Callable[[str], ProviderCatalog]], ...] = (
    ("acp", _acp_catalog),
    ("codex", _codex_catalog),
    ("kimi", _kimi_catalog),
    ("openai", _openai_catalog),
)


@pytest.mark.parametrize(("lane", "normalize"), _DISPLAY_LANES)
def test_a_lane_keeps_a_display_name_at_exactly_the_declared_cap(
    lane: str, normalize: Callable[[str], ProviderCatalog]
) -> None:
    """A name of exactly the cap must survive the lane unshortened."""
    name = "n" * MAX_DISPLAY_LENGTH

    catalog = normalize(name)

    assert catalog.models[0].display_name == name, (
        f"{lane} shortened a display name the model accepts whole; it kept "
        f"{len(catalog.models[0].display_name)} of {MAX_DISPLAY_LENGTH} "
        "characters, for a reason stated nowhere"
    )


@pytest.mark.parametrize(("lane", "normalize"), _DISPLAY_LANES)
def test_a_lane_bounds_a_longer_display_name_instead_of_losing_the_catalog(
    lane: str, normalize: Callable[[str], ProviderCatalog]
) -> None:
    """One character past the cap is truncated, not refused."""
    catalog = normalize("n" * (MAX_DISPLAY_LENGTH + 1))

    display_name = catalog.models[0].display_name
    assert len(display_name) == MAX_DISPLAY_LENGTH, (
        f"{lane} produced a {len(display_name)}-character display name against "
        f"a {MAX_DISPLAY_LENGTH}-character bound"
    )


@pytest.mark.parametrize(("lane", "normalize"), _DISPLAY_LANES)
@pytest.mark.parametrize("phase", _PHASES)
def test_a_lane_survives_a_display_name_cut_on_a_space(
    lane: str, normalize: Callable[[str], ProviderCatalog], phase: int
) -> None:
    """A cut landing on a space must not cost the catalog.

    The model demands a bounded string AND a normalized one. Truncation alone
    satisfies the first and can break the second, and every lane truncated, so
    every lane lost whole catalogs to a provider label that merely happened to
    have a space at the cut point. Sweeping the phase lands a space exactly on
    the cut for one of them whatever fixed prefix a lane composes in front.
    """
    catalog = normalize(_spaced_name(phase, length=MAX_DISPLAY_LENGTH * 2))

    labels = [catalog.models[0].display_name]
    labels.extend(control.display_name for control in catalog.native_controls)
    for label in labels:
        assert label == label.strip(), (
            f"{lane} built an unnormalized label at phase {phase}: {label[-8:]!r}"
        )
        assert len(label) <= MAX_DISPLAY_LENGTH, f"{lane} exceeded the bound"


def test_the_shared_helper_normalizes_the_exact_boundary_cut() -> None:
    """The helper both bounds and re-normalizes, at the precise cut point."""
    name = "a" * (MAX_DISPLAY_LENGTH - 1) + " " + "tail beyond the cap"

    label = display_label(name)

    assert label == "a" * (MAX_DISPLAY_LENGTH - 1)
    assert len(label) < MAX_DISPLAY_LENGTH
    assert label == label.strip()


def test_a_description_cut_on_a_space_stays_normalized() -> None:
    """The description bound carries the same obligation as the display bound."""
    description = "a" * (MAX_TEXT_LENGTH - 1) + " " + "tail beyond the cap"

    text = optional_description(description)

    assert text is not None
    assert text == text.strip()
    assert len(text) <= MAX_TEXT_LENGTH


def _kimi_capabilities(count: int) -> ProviderCatalog:
    """Normalize a Kimi alias advertising *count* capabilities."""
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
                        "capabilities": [f"cap-{index}" for index in range(count)],
                    }
                },
            },
        ),
        key=_KEY,
    )


def test_the_lane_admits_capabilities_at_exactly_the_declared_cap() -> None:
    """The cap exactly must survive the lane and the model."""
    catalog = _kimi_capabilities(MAX_CAPABILITIES)

    assert len(catalog.models[0].capabilities) == MAX_CAPABILITIES, (
        "kimi admitted the catalog but kept "
        f"{len(catalog.models[0].capabilities)} of {MAX_CAPABILITIES} "
        "capabilities; a lane that silently truncates advertises a model the "
        "provider did not offer"
    )


def test_the_lane_refuses_one_capability_beyond_the_declared_cap() -> None:
    """One past the cap is refused in the lane's own dialect.

    Capabilities are COUNTED rather than truncated, at the lane and at the model
    alike - unlike the display bound, where both sides settled on cutting. The
    refusal type is asserted because the bound is shared and the mapping is not.
    """
    with pytest.raises(KimiCatalogProtocolError, match=f"exceeds {MAX_CAPABILITIES}"):
        _kimi_capabilities(MAX_CAPABILITIES + 1)
