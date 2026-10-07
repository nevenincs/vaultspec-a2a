"""``PlanEntry`` is carried by the run snapshot but declared by exactly one module.

The run snapshot is the Layer-1 dataclass ``ThreadStateData`` and this
subpackage declares no mirror of it. ``PlanEntry`` is a domain dataclass
belonging to ``vaultspec_a2a.thread.models``, which the snapshot merely carries
as a field type, exactly as it carries ``ThreadStatus``, ``ToolKind``, and
``Provider`` without re-exporting those either.

Being visible on the wire is what makes that easy to get wrong, so the tests pin
each half. The type really is the domain one - asserted through the snapshot's
own declared annotation and a real round-trip, not by inspecting an import
statement - the schemas facade does not offer a second name for it, and the
subpackage holds no module that would restate the snapshot.
"""

import dataclasses
import importlib.util
import typing

from pydantic import TypeAdapter

from ....thread.enums import ThreadStatus
from ....thread.models import PlanEntry
from ....thread.snapshots import ThreadStateData
from ... import schemas as facade


def test_the_snapshot_declares_the_domain_type_itself() -> None:
    """The plan-bearing snapshot annotates the ``thread.models`` class, not a copy.

    An identity check rather than a name check: a duplicate dataclass declared
    elsewhere would carry the same name, the same fields, and would serialize
    identically, so comparing ``__name__`` would pass against exactly the defect
    a copied type introduces.
    """
    annotations = {f.name: f.type for f in dataclasses.fields(ThreadStateData)}
    (item_type,) = typing.get_args(annotations["plan"])

    assert item_type is PlanEntry
    assert item_type.__module__ == "vaultspec_a2a.thread.models"


def test_a_domain_entry_survives_validation_as_the_domain_type() -> None:
    """Real construction and round-trip, so the annotation is not merely decorative."""
    adapter = TypeAdapter(ThreadStateData)
    snapshot = ThreadStateData(
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

    revived = adapter.validate_python(adapter.dump_python(snapshot))

    assert all(isinstance(entry, PlanEntry) for entry in revived.plan)
    assert revived.plan[0].content == "Implement feature"
    assert revived.plan[1].status == "pending"
    assert revived.plan == snapshot.plan


def test_the_schemas_facade_offers_no_second_name_for_it() -> None:
    """The removed declaration.

    ``from vaultspec_a2a.api.schemas import PlanEntry`` raises exactly when the
    attribute lookup below fails, so this is the whole statement rather than a
    proxy for it: the facade neither advertises the name nor answers to it.
    """
    assert "PlanEntry" not in facade.__all__
    assert not hasattr(facade, "PlanEntry")


def test_the_subpackage_holds_no_second_declaration_of_the_snapshot() -> None:
    """There is no wire mirror module, and the facade names no snapshot type.

    The snapshot has one declaration, in ``thread.snapshots``. A module here that
    restated it would reintroduce the second copy a parity test had to chase, so
    neither a ``snapshots`` module nor a facade name for the snapshot may return.
    """
    assert importlib.util.find_spec(f"{facade.__name__}.snapshots") is None
    assert not hasattr(facade, "ThreadStateSnapshot")
    assert not hasattr(facade, "ThreadStateData")
