"""``PlanEntry`` is carried by the wire models but declared by exactly one module.

This subpackage's facade re-exports the types it OWNS. ``PlanEntry`` is not one
of them: it is a domain dataclass belonging to ``vaultspec_a2a.thread.models``,
which the wire models merely carry as a field type, exactly as they carry
``ThreadStatus``, ``ToolKind``, and ``Provider`` without re-exporting those
either.

Being visible on the wire is what makes that easy to get wrong, so the test
pins both halves. The type really is the domain one - asserted through the
model's own declared annotation and a real round-trip, not by inspecting an
import statement - and the facade does not offer a second name for it.

The last test is the one that keeps the other two honest. A facade that failed
to import, or that exported nothing at all, would satisfy every "PlanEntry is
absent" assertion here for entirely the wrong reason, so the surface that is
supposed to remain is asserted as well.
"""

from __future__ import annotations

import typing

from ....thread.enums import ThreadStatus
from ....thread.models import PlanEntry
from ... import schemas as facade
from .. import ThreadStateSnapshot


def test_the_wire_model_declares_the_domain_type_itself() -> None:
    """The plan-bearing model annotates the ``thread.models`` class, not a copy.

    An identity check rather than a name check: a duplicate dataclass declared
    elsewhere would carry the same name, the same fields, and would serialize
    identically, so comparing ``__name__`` would pass against exactly the defect
    this campaign retires.
    """
    annotation = ThreadStateSnapshot.model_fields["plan"].annotation
    (item_type,) = typing.get_args(annotation)

    assert item_type is PlanEntry
    assert item_type.__module__ == "vaultspec_a2a.thread.models"


def test_a_domain_entry_survives_validation_as_the_domain_type() -> None:
    """Real construction and round-trip, so the annotation is not merely decorative."""
    snapshot = ThreadStateSnapshot(
        thread_id="thread-plan",
        status=ThreadStatus.RUNNING,
        last_sequence=1,
        plan=[
            PlanEntry(
                content="Implement feature", status="in_progress", priority="high"
            ),
            PlanEntry(content="Write tests"),
        ],
    )

    assert all(isinstance(entry, PlanEntry) for entry in snapshot.plan)
    assert snapshot.plan[0].content == "Implement feature"
    assert snapshot.plan[1].status == "pending"

    revived = ThreadStateSnapshot.model_validate(snapshot.model_dump())
    assert revived.plan == snapshot.plan


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
    assertion in this module. The snapshot model that carries ``PlanEntry`` is
    the sharpest witness: it is still here, so the absence of ``PlanEntry`` is a
    decision rather than an outage.
    """
    assert "ThreadStateSnapshot" in facade.__all__
    assert hasattr(facade, "ThreadStateSnapshot")

    assert all(hasattr(facade, name) for name in facade.__all__)
