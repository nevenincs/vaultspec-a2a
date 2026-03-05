"""Persistence layer for the orchestrator.

Facade re-exporting all public types from the ``lib.database`` subpackage.
Consumers should import from this module rather than reaching into
sub-modules directly::

    from lib.database import init_db, create_thread, ThreadModel
"""

from .crud import ThreadStatus as ThreadStatus
from .crud import append_cost_record as append_cost_record
from .crud import append_permission_log as append_permission_log
from .crud import create_artifact as create_artifact
from .crud import create_thread as create_thread
from .crud import get_artifact as get_artifact
from .crud import get_artifacts_by_thread as get_artifacts_by_thread
from .crud import get_permission_logs_by_thread as get_permission_logs_by_thread
from .crud import get_thread as get_thread
from .crud import get_thread_metadata as get_thread_metadata
from .crud import list_threads as list_threads
from .crud import save_model as save_model
from .crud import sum_cost_by_agent as sum_cost_by_agent
from .crud import sum_cost_by_thread as sum_cost_by_thread
from .crud import update_thread_metadata as update_thread_metadata
from .crud import update_thread_status as update_thread_status
from .models import ArtifactModel as ArtifactModel
from .models import Base as Base
from .models import CostTrackingModel as CostTrackingModel
from .models import PermissionLogModel as PermissionLogModel
from .models import ThreadModel as ThreadModel
from .session import close_db as close_db
from .session import get_db as get_db
from .session import get_engine as get_engine
from .session import get_session_factory as get_session_factory
from .session import init_db as init_db
from .session import verify_wal_mode as verify_wal_mode
from .migrate import run_migrations as run_migrations

__all__ = [
    "ArtifactModel",
    "Base",
    "CostTrackingModel",
    "PermissionLogModel",
    "ThreadModel",
    "ThreadStatus",
    "append_cost_record",
    "append_permission_log",
    "close_db",
    "create_artifact",
    "create_thread",
    "get_artifact",
    "get_artifacts_by_thread",
    "get_db",
    "get_engine",
    "get_permission_logs_by_thread",
    "get_session_factory",
    "get_thread",
    "get_thread_metadata",
    "init_db",
    "list_threads",
    "run_migrations",
    "save_model",
    "sum_cost_by_agent",
    "sum_cost_by_thread",
    "update_thread_metadata",
    "update_thread_status",
    "verify_wal_mode",
]
