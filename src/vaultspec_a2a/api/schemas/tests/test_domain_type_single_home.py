"""``PlanEntry`` is carried by the wire models but declared by exactly one module.

This subpackage's facade re-exports the types it OWNS. ``PlanEntry`` is not one
of them: it is a domain dataclass belonging to ``vaultspec_a2a.thread.models``,
which the wire models merely carry as a field type, exactly as they carry
``ThreadStatus``, ``ToolKind``, and ``Provider`` without re-exporting those
either. It reached the facade through ``events``, which imports it as a
dependency and deliberately leaves it out of its own ``__all__`` - so the facade
was declaring a public surface its source module disclaimed.

Being visible on the wire is what makes that easy to get wrong, so the test
pins both halves. The type really is the domain one - asserted through the
models' own declared annotations and a real round-trip, not by inspecting an
import statement - and the facade does not offer a second name for it.

The last test is the one that keeps the other two honest. A facade that failed
to import, or that exported nothing at all, would satisfy every "PlanEntry is
absent" assertion here for entirely the wrong reason, so the surface that is
supposed to remain is asserted as well.
"""

from __future__ import annotations

import typing
from typing import TYPE_CHECKING

import pytest

from ....thread.models import PlanEntry
from ... import schemas as facade
from .. import PlanEntryPriority, PlanEntryStatus, PlanUpdateEvent, ThreadStateSnapshot
from .test_schemas import ENVELOPE

if TYPE_CHECKING:
    from pydantic import BaseModel


@pytest.mark.parametrize(
    ("model", "field"),
    [(PlanUpdateEvent, "entries"), (ThreadStateSnapshot, "plan")],
)
def test_the_wire_models_declare_the_domain_type_itself(
    model: type[BaseModel], field: str
) -> None:
    """Both plan-bearing models annotate the ``thread.models`` class, not a copy.

    An identity check rather than a name check: a duplicate dataclass declared
    elsewhere would carry the same name, the same fields, and would serialize
    identically, so comparing ``__name__`` would pass against exactly the defect
    this campaign retires.
    """
    annotation = model.model_fields[field].annotation
    (item_type,) = typing.get_args(annotation)

    assert item_type is PlanEntry
    assert item_type.__module__ == "vaultspec_a2a.thread.models"


def test_a_domain_entry_survives_validation_as_the_domain_type() -> None:
    """Real construction and round-trip, so the annotation is not merely decorative."""
    event = PlanUpdateEvent(
        **ENVELOPE,
        entries=[
            PlanEntry(
                content="Implement feature",
                status=PlanEntryStatus.IN_PROGRESS,
                priority=PlanEntryPriority.HIGH,
            ),
            PlanEntry(content="Write tests"),
        ],
    )

    assert all(isinstance(entry, PlanEntry) for entry in event.entries)
    assert event.entries[0].content == "Implement feature"
    assert event.entries[1].status == "pending"

    revived = PlanUpdateEvent.model_validate(event.model_dump())
    assert revived.entries == event.entries


def test_the_schemas_facade_offers_no_second_name_for_it() -> None:
    """The removed declaration.

    ``from vaultspec_a2a.api.schemas import PlanEntry`` raises exactly when the
    attribute lookup below fails, so this is the whole statement rather than a
    proxy for it: the facade neither advertises the name nor answers to it.
    """
    assert "PlanEntry" not in facade.__all__
    assert not hasattr(facade, "PlanEntry")


def test_the_facade_still_declares_the_types_it_does_own() -> None:
    """Why the refusal above happens - the facade is populated, not broken.

    Without this, a facade whose imports had failed outright would pass every
    assertion in this module. The wire-only siblings of ``PlanEntry`` on the
    same two models are the sharpest witnesses: they are still here, so the
    absence of ``PlanEntry`` is a decision rather than an outage.
    """
    for owned in ("PlanUpdateEvent", "ThreadStateSnapshot", "ServerEvent"):
        assert owned in facade.__all__
        assert hasattr(facade, owned)

    # The API-only enums that describe a PlanEntry's values DO belong here.
    for owned in ("PlanEntryStatus", "PlanEntryPriority"):
        assert owned in facade.__all__
        assert hasattr(facade, owned)

    assert all(hasattr(facade, name) for name in facade.__all__)
