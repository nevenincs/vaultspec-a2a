from lib.api import Message, Session, router
from lib.core import PermissionEngine, Registry, TeamState


def test_facade_imports():
    """Verify that we can import from the sub-module root (facade)."""
    assert router == "router_placeholder"
    assert Message is not None
    assert Session is not None
    assert PermissionEngine is not None
    assert Registry is not None
    assert TeamState is not None


def test_direct_imports_discouraged():
    """Verify that sub-sub-modules are accessible but imports should use facades."""
    from lib.api.schemas import Message as SchemaMessage

    assert SchemaMessage is Message
