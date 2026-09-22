"""Real Linux proof for the Compose provider/service identity boundary."""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = REPO_ROOT / "service" / "docker" / "prod.Dockerfile"


def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    docker = shutil.which("docker") or shutil.which("docker.exe")
    if docker is None:
        raise RuntimeError("Docker CLI is required for provider isolation proof")
    return subprocess.run(
        [docker, *arguments],
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
        timeout=600,
    )


@pytest.fixture(scope="module")
def boundary_image_and_volumes() -> Iterator[tuple[str, str, str]]:
    """Build one isolated proof image and exact named volumes, then clean them."""
    suffix = uuid.uuid4().hex[:12]
    image = f"vaultspec-s10-proof-{suffix}"
    data_volume = f"vaultspec-s10-data-{suffix}"
    state_volume = f"vaultspec-s10-state-{suffix}"
    _docker(
        "build",
        "--target",
        "worker",
        "--tag",
        image,
        "--file",
        str(DOCKERFILE),
        ".",
    )
    _docker("volume", "create", data_volume)
    _docker("volume", "create", state_volume)
    try:
        yield image, data_volume, state_volume
    finally:
        _docker("volume", "rm", "--force", data_volume, state_volume, check=False)
        _docker("image", "rm", "--force", image, check=False)


def _seed_preexisting_state(image: str, data_volume: str, state_volume: str) -> None:
    script = """
import os
from pathlib import Path

workspace = Path('/app/data/workspaces/project')
workspace.mkdir(parents=True, exist_ok=True)
os.chown('/app/data/workspaces', 1001, 1001)
os.chmod('/app/data/workspaces', 0o755)
os.chown(workspace, 1001, 1001)
os.chmod(workspace, 0o755)
visible = workspace / 'visible.txt'
visible.write_text('workspace-data', encoding='utf-8')
os.chown(visible, 1001, 1001)
os.chmod(visible, 0o644)
executable = workspace / 'legacy-tool'
executable.write_text('#!/bin/sh\\nprintf legacy-executable', encoding='utf-8')
os.chown(executable, 1001, 1001)
os.chmod(executable, 0o755)

database = Path('/app/data/vaultspec.db')
database.write_text('database-secret', encoding='utf-8')
os.chown(database, 1001, 1001)
os.chmod(database, 0o644)

token = Path('/app/worker-state/service.token')
token.parent.mkdir(parents=True, exist_ok=True)
token.write_text('service-token-secret', encoding='utf-8')
os.chown(token.parent, 1001, 1001)
os.chown(token, 1001, 1001)
os.chmod(token, 0o644)
"""
    _docker(
        "run",
        "--rm",
        "--user",
        "0",
        "--entrypoint",
        "/app/.venv/bin/python",
        "--volume",
        f"{data_volume}:/app/data",
        "--volume",
        f"{state_volume}:/app/worker-state",
        image,
        "-c",
        script,
    )


def test_real_provider_child_cannot_read_service_state(
    boundary_image_and_volumes: tuple[str, str, str],
) -> None:
    """Exercise entrypoint repair and the actual launcher with no mocked boundary."""
    image, data_volume, state_volume = boundary_image_and_volumes
    _seed_preexisting_state(image, data_volume, state_volume)
    child = """
import json
import os
import subprocess
from pathlib import Path

result = {
    'uid': os.getuid(),
    'gid': os.getgid(),
    'groups': os.getgroups(),
    'provider_auth': os.environ.get('ANTHROPIC_AUTH_TOKEN'),
    'service_env': sorted(
        key for key in os.environ
        if key.startswith('VAULTSPEC_')
        or key in {'DATABASE_URL', 'INTERNAL_TOKEN'}
    ),
    'cmdline': Path('/proc/self/cmdline').read_bytes().decode(errors='replace'),
    'workspace': Path('visible.txt').read_text(encoding='utf-8'),
    'callback_created': Path('callback-created.txt').read_text(encoding='utf-8'),
    'legacy_executable': subprocess.check_output(['./legacy-tool'], text=True),
}
Path('agent-created.txt').write_text('agent-write', encoding='utf-8')
for name, path in {
    'database': Path('/app/data/vaultspec.db'),
    'fresh_database': Path('/app/data/fresh.db'),
    'token': Path('/app/worker-state/service.token'),
}.items():
    try:
        path.read_text(encoding='utf-8')
    except PermissionError:
        result[name] = 'denied'
    else:
        result[name] = 'READABLE'
status = dict(
    line.split(':', 1)
    for line in Path('/proc/self/status').read_text(encoding='utf-8').splitlines()
    if ':' in line
)
result['caps'] = {
    name: status[name].strip()
    for name in ('CapInh', 'CapPrm', 'CapEff', 'CapAmb')
}
result['no_new_privs'] = status['NoNewPrivs'].strip()
print(json.dumps(result, sort_keys=True))
"""
    parent = f"""
import asyncio
import json
import sys
from pathlib import Path

from vaultspec_a2a.providers import _acp_rpc_handlers as handlers
from vaultspec_a2a.providers._subprocess import spawn_acp_process
from vaultspec_a2a.workspace.environment import resolve_env_vars

class Config:
    workspace_root = '/app/data/workspaces/project'

async def main():
    workspace = Path('/app/data/workspaces/project')
    Path('/app/data/fresh.db').write_text('fresh-database-state', encoding='utf-8')
    callback_write = await handlers.on_fs_write_text_file(
        1,
        {{'path': 'callback-created.txt', 'content': 'callback-write'}},
        None,
        Config(),
    )
    if callback_write.get('result') != {{}}:
        raise RuntimeError(str(callback_write))
    environment = resolve_env_vars(workspace)
    process = await spawn_acp_process(
        [sys.executable, '-c', {child!r}],
        environment,
        str(workspace),
        use_exec=True,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors='replace'))
    result = json.loads(stdout.decode())
    callback_read = await handlers.on_fs_read_text_file(
        2, {{'path': 'agent-created.txt'}}, None, Config()
    )
    result['callback_read'] = callback_read['result']['content']
    callback_update = await handlers.on_fs_write_text_file(
        3, {{'path': 'agent-created.txt', 'content': 'callback-update'}}, None, Config()
    )
    if callback_update.get('result') != {{}}:
        raise RuntimeError(str(callback_update))
    verify = await spawn_acp_process(
        [sys.executable, '-c', "from pathlib import Path; "
         "print(Path('agent-created.txt').read_text())"],
        environment,
        str(workspace),
        use_exec=True,
    )
    verify_stdout, verify_stderr = await verify.communicate()
    if verify.returncode != 0:
        raise RuntimeError(verify_stderr.decode(errors='replace'))
    result['agent_read_after_callback'] = verify_stdout.decode().strip()
    print(json.dumps(result, sort_keys=True))

asyncio.run(main())
"""
    completed = _docker(
        "run",
        "--rm",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "SETUID",
        "--cap-add",
        "SETGID",
        "--volume",
        f"{data_volume}:/app/data",
        "--volume",
        f"{state_volume}:/app/worker-state",
        "--env",
        "VAULTSPEC_WORKSPACE_ROOT=/app/data/workspaces",
        "--env",
        "VAULTSPEC_A2A_HOME=/app/worker-state",
        "--env",
        "VAULTSPEC_DATABASE_URL=sqlite+aiosqlite:////app/data/vaultspec.db",
        "--env",
        "VAULTSPEC_CHECKPOINT_DATABASE_URL=sqlite+aiosqlite:////app/data/fresh.db",
        "--env",
        "VAULTSPEC_PROVIDER_IDENTITY_LAUNCHER=/usr/local/bin/vaultspec-agent-launch",
        "--env",
        "VAULTSPEC_PROVIDER_AGENT_UID=1002",
        "--env",
        "VAULTSPEC_PROVIDER_AGENT_GID=1002",
        "--env",
        "VAULTSPEC_MANAGED_WORKSPACE_PERMISSIONS=true",
        "--env",
        "VAULTSPEC_INTERNAL_TOKEN=internal-secret-value",
        "--env",
        "DATABASE_URL=database-secret-value",
        "--env",
        "ANTHROPIC_AUTH_TOKEN=intended-provider-auth",
        image,
        "/app/.venv/bin/python",
        "-c",
        parent,
    )
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["uid"] == 1002
    assert result["gid"] == 1002
    assert result["groups"] == []
    assert result["caps"] == {
        "CapInh": "0000000000000000",
        "CapPrm": "0000000000000000",
        "CapEff": "0000000000000000",
        "CapAmb": "0000000000000000",
    }
    assert result["no_new_privs"] == "1"
    assert result["workspace"] == "workspace-data"
    assert result["callback_created"] == "callback-write"
    assert result["legacy_executable"] == "legacy-executable"
    assert result["callback_read"] == "agent-write"
    assert result["agent_read_after_callback"] == "callback-update"
    assert result["database"] == "denied"
    assert result["fresh_database"] == "denied"
    assert result["token"] == "denied"
    assert result["service_env"] == []
    assert result["provider_auth"] == "intended-provider-auth"
    assert "internal-secret-value" not in result["cmdline"]
    assert "database-secret-value" not in result["cmdline"]

    modes = _docker(
        "run",
        "--rm",
        "--user",
        "0",
        "--entrypoint",
        "/app/.venv/bin/python",
        "--volume",
        f"{data_volume}:/app/data",
        "--volume",
        f"{state_volume}:/app/worker-state",
        image,
        "-c",
        "import json,stat; from pathlib import Path; "
        "print(json.dumps({str(p): oct(stat.S_IMODE(p.stat().st_mode)) for p in "
        "map(Path, ['/app/data/vaultspec.db','/app/data/fresh.db',"
        "'/app/worker-state/service.token',"
        "'/app/data/workspaces/project/agent-created.txt',"
        "'/app/data/workspaces/project/callback-created.txt',"
        "'/app/data/workspaces/project/legacy-tool'])}))",
    )
    repaired = json.loads(modes.stdout.strip())
    assert repaired["/app/data/vaultspec.db"] == "0o600"
    assert repaired["/app/data/fresh.db"] == "0o600"
    assert repaired["/app/worker-state/service.token"] == "0o644"
    assert repaired["/app/data/workspaces/project/agent-created.txt"] == "0o660"
    assert repaired["/app/data/workspaces/project/callback-created.txt"] == "0o660"
    assert repaired["/app/data/workspaces/project/legacy-tool"] == "0o775"


def test_linux_callback_race_and_launcher_failure_proofs(
    boundary_image_and_volumes: tuple[str, str, str],
) -> None:
    """Run real Linux descriptor races and launcher fail-closed proofs in-image."""
    image, _, _ = boundary_image_and_volumes
    proof = """
import asyncio
import json
import os
import tempfile
from pathlib import Path

from vaultspec_a2a.control.config import settings
from vaultspec_a2a.providers import _acp_rpc_handlers as handlers
from vaultspec_a2a.providers._subprocess import _provider_execution_command
from vaultspec_a2a.utils.process import ProcessContainmentError

class Config:
    workspace_root: str

root = Path(tempfile.mkdtemp(prefix='vaultspec-callback-proof-'))
managed = root / 'managed'
managed.mkdir()
bound = managed / 'bound'
protected = root / 'service-state'
bound.mkdir()
protected.mkdir()
Config.workspace_root = str(bound)
settings.provider_identity_launcher = Path('/configured')
settings.workspace_root = managed
settings.provider_agent_gid = 1002

root_race = managed / 'switch' / 'data'
root_race.mkdir(parents=True)
(root_race / 'root-race-secret.txt').write_text('workspace-data', encoding='utf-8')
service_secret = Path('/app/data/root-race-secret.txt')
service_secret.write_text('service-secret', encoding='utf-8')
Config.workspace_root = str(root_race)
real_open = handlers.os.open
swapped_root = False

def run_root_race(path, flags, *args, **kwargs):
    global swapped_root
    if path == managed and not swapped_root:
        swapped_root = True
        (managed / 'switch').rename(managed / 'parked-switch')
        (managed / 'switch').symlink_to('/app', target_is_directory=True)
    return real_open(path, flags, *args, **kwargs)

handlers.os.open = run_root_race
root_component_escape = asyncio.run(handlers.on_fs_read_text_file(
    0, {'path': 'root-race-secret.txt'}, None, Config()
))
assert 'error' in root_component_escape
assert 'service-secret' not in str(root_component_escape)
handlers.os.open = real_open

replaced = managed / 'replaced'
replaced.symlink_to(protected, target_is_directory=True)
(protected / 'service.token').write_text('service-secret', encoding='utf-8')
Config.workspace_root = str(replaced)
root_escape = asyncio.run(handlers.on_fs_read_text_file(
    0, {'path': 'service.token'}, None, Config()
))
assert 'error' in root_escape
assert 'service-secret' not in str(root_escape)
Config.workspace_root = str(bound)

safe = bound / 'safe'
parked = bound / 'parked'
safe.mkdir()
(safe / 'data.txt').write_text('workspace-data', encoding='utf-8')
(protected / 'data.txt').write_text('service-secret', encoding='utf-8')
swapped = False

def read_race(path, flags, *args, **kwargs):
    global swapped
    if path == 'data.txt' and kwargs.get('dir_fd') is not None and not swapped:
        swapped = True
        safe.rename(parked)
        safe.symlink_to(protected, target_is_directory=True)
    return real_open(path, flags, *args, **kwargs)

handlers.os.open = read_race
read = asyncio.run(handlers.on_fs_read_text_file(
    1, {'path': 'safe/data.txt'}, None, Config()
))
assert read['result']['content'] == 'workspace-data'
handlers.os.open = real_open
safe.unlink()
parked.rename(safe)
parked = bound / 'parked-write'
protected_target = protected / 'target.txt'
protected_target.write_text('service-state', encoding='utf-8')
swapped = False

def write_race(path, flags, *args, **kwargs):
    global swapped
    if path == 'target.txt' and kwargs.get('dir_fd') is not None and not swapped:
        swapped = True
        safe.rename(parked)
        safe.symlink_to(protected, target_is_directory=True)
    return real_open(path, flags, *args, **kwargs)

handlers.os.open = write_race
written = asyncio.run(handlers.on_fs_write_text_file(
    2, {'path': 'safe/target.txt', 'content': 'workspace-write'}, None, Config()
))
assert written['result'] == {}
assert protected_target.read_text(encoding='utf-8') == 'service-state'
assert (parked / 'target.txt').read_text(encoding='utf-8') == 'workspace-write'
handlers.os.open = real_open
safe.unlink()
real_mkdir = handlers.os.mkdir
created = bound / 'created'
parked_created = bound / 'parked-created'

def create_race(path, *args, **kwargs):
    result = real_mkdir(path, *args, **kwargs)
    if path == 'created' and kwargs.get('dir_fd') is not None:
        created.rename(parked_created)
        created.symlink_to(protected, target_is_directory=True)
    return result

handlers.os.mkdir = create_race
create_result = asyncio.run(handlers.on_fs_write_text_file(
    3,
    {'path': 'created/child.txt', 'content': 'must-stay-in-workspace'},
    None,
    Config(),
))
assert 'error' in create_result
assert not (protected / 'child.txt').exists()

settings.provider_agent_uid = 1002
settings.provider_agent_gid = None
try:
    _provider_execution_command(['python', 'provider.py'])
except ProcessContainmentError:
    partial_failed_closed = True
else:
    partial_failed_closed = False
assert partial_failed_closed
print(json.dumps({
    'create_race': 'failed-closed',
    'read_race': 'anchored',
    'root_escape': 'denied',
    'root_component_race': 'denied',
    'write_race': 'anchored',
}))
"""
    completed = _docker(
        "run",
        "--rm",
        "--entrypoint",
        "/app/.venv/bin/python",
        image,
        "-c",
        proof,
    )
    assert json.loads(completed.stdout.strip()) == {
        "create_race": "failed-closed",
        "read_race": "anchored",
        "root_escape": "denied",
        "root_component_race": "denied",
        "write_race": "anchored",
    }

    denied = _docker(
        "run",
        "--rm",
        "--user",
        "1001:1001",
        "--cap-drop",
        "ALL",
        "--entrypoint",
        "/usr/local/bin/vaultspec-agent-launch",
        image,
        "1002",
        "1002",
        "--",
        "/app/.venv/bin/python",
        "-c",
        "raise SystemExit('must not execute')",
        check=False,
    )
    assert denied.returncode == 126
    assert "failed" in denied.stderr


def test_managed_workspace_migration_refuses_hardlinks_without_touching_target(
    boundary_image_and_volumes: tuple[str, str, str],
) -> None:
    """A workspace hard link cannot make migration rewrite service state."""
    image, _, _ = boundary_image_and_volumes
    volume = f"vaultspec-s10-hardlink-{uuid.uuid4().hex[:12]}"
    _docker("volume", "create", volume)
    try:
        seed = """
import os
from pathlib import Path

workspace = Path('/app/data/workspaces/project')
workspace.mkdir(parents=True, exist_ok=True)
database = Path('/app/data/vaultspec.db')
database.write_text('database-secret', encoding='utf-8')
os.chown('/app/data/workspaces', 1001, 1001)
os.chown(workspace, 1001, 1001)
os.chown(database, 1001, 1001)
os.chmod(database, 0o644)
os.link(database, workspace / 'database-link')
"""
        _docker(
            "run",
            "--rm",
            "--user",
            "0",
            "--entrypoint",
            "/app/.venv/bin/python",
            "--volume",
            f"{volume}:/app/data",
            image,
            "-c",
            seed,
        )
        refused = _docker(
            "run",
            "--rm",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "SETUID",
            "--cap-add",
            "SETGID",
            "--volume",
            f"{volume}:/app/data",
            "--env",
            "VAULTSPEC_WORKSPACE_ROOT=/app/data/workspaces",
            "--env",
            "VAULTSPEC_A2A_HOME=/app/worker-state",
            "--env",
            "VAULTSPEC_PROVIDER_IDENTITY_LAUNCHER=/usr/local/bin/vaultspec-agent-launch",
            "--env",
            "VAULTSPEC_PROVIDER_AGENT_UID=1002",
            "--env",
            "VAULTSPEC_PROVIDER_AGENT_GID=1002",
            "--env",
            "VAULTSPEC_MANAGED_WORKSPACE_PERMISSIONS=true",
            image,
            "/bin/true",
            check=False,
        )
        assert refused.returncode != 0
        assert "hard-linked file" in refused.stderr

        mode = _docker(
            "run",
            "--rm",
            "--user",
            "0",
            "--entrypoint",
            "/app/.venv/bin/python",
            "--volume",
            f"{volume}:/app/data",
            image,
            "-c",
            "import os,stat; s=os.stat('/app/data/vaultspec.db'); "
            "print(f'{s.st_gid}:{stat.S_IMODE(s.st_mode):o}')",
        )
        assert mode.stdout.strip() == "1001:644"
    finally:
        _docker("volume", "rm", "--force", volume, check=False)
