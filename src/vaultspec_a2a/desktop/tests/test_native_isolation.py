"""Actual filesystem and native-process controls for Linux path-bound isolation."""

from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import override

import pytest

from ...utils.process import ProcessContainmentError
from .._linux_runtime_assets import stage_linux_isolation_assets
from ..native_isolation import NativeLaunchAuthority, linux_isolated_command
from ..profile import derive_state_paths


def _authority(tmp_path: Path) -> NativeLaunchAuthority:
    app_home = tmp_path / "app"
    capsule = tmp_path / "capsule"
    state = derive_state_paths(app_home)
    workspace = state.workspaces_root / "project"
    home = state.temp_homes_dir / "codex-run-selected"
    workspace.mkdir(parents=True)
    home.mkdir(parents=True)
    capsule.mkdir()
    return NativeLaunchAuthority.issue(
        app_home=app_home, capsule=capsule, workspace=workspace, home=home
    )


def _install_runtime(authority: NativeLaunchAuthority) -> Path:
    node = Path("/usr/bin/node")
    target = authority.capsule.path / "node" / "bin" / "node"
    target.parent.mkdir(parents=True)
    shutil.copyfile(node, target)
    target.chmod(node.stat().st_mode & 0o777)
    dependencies = subprocess.run(
        ["ldd", str(node)], check=True, capture_output=True, text=True
    ).stdout
    # Discovery is confined to the test producer. The launched helper receives
    # only the production build-owned manifest; it never searches the host.
    paths = set(re.findall(r"(/[^\s()]+)", dependencies))
    stage_linux_isolation_assets(
        authority.capsule.path,
        helper=Path("/usr/bin/bwrap"),
        files={path: Path(path) for path in paths},
    )
    return target


def test_authority_cannot_grant_private_state_or_all_role_homes(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    private = authority.app_home.path / "credentials"
    private.mkdir()
    state = derive_state_paths(authority.app_home.path)
    for workspace, home in (
        (private, authority.home.path),
        (authority.workspace.path, state.temp_homes_dir),
        (authority.workspace.path, private),
    ):
        with pytest.raises(ValueError):
            NativeLaunchAuthority.issue(
                app_home=authority.app_home.path,
                capsule=authority.capsule.path,
                workspace=workspace,
                home=home,
            )
    with pytest.raises(ValueError, match="cwd"):
        authority.canonical_cwd(str(private))
    assert authority.canonical_cwd(str(authority.workspace.path)) == str(
        authority.workspace.path
    )
    assert NativeLaunchAuthority.decode(authority.encode()) == authority


def test_replaced_project_cannot_reuse_issued_authority(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    authority.workspace.path.rename(authority.workspace.path.with_name("original"))
    authority.workspace.path.mkdir()
    with pytest.raises(OSError, match="changed"):
        authority.validate()


def test_authority_metadata_refuses_ambiguous_or_unbounded_input(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    encoded = authority.encode()
    root = json.loads(encoded)["app_home"]
    ambiguous = encoded[:-1] + ', "app_home": ' + json.dumps(root) + "}"
    for malformed in (ambiguous, "x" * 65537, "[" * 2000 + "]" * 2000):
        with pytest.raises(ValueError):
            NativeLaunchAuthority.decode(malformed)


def test_native_grants_preserve_work_and_deny_other_planes(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    if sys.platform != "linux":
        with pytest.raises(ProcessContainmentError, match="requires Linux"):
            linux_isolated_command(authority, [sys.executable], cwd=str(tmp_path))
        return
    node = _install_runtime(authority)
    private = authority.app_home.path / "credentials"
    private.mkdir()
    secret = private / "lifecycle-token"
    secret.write_text("synthetic-control-plane", encoding="utf-8")
    other_home = authority.home.path.with_name("codex-run-other")
    other_home.mkdir()
    (other_home / "auth.json").write_text("synthetic-other-role", encoding="utf-8")
    (authority.home.path / "auth.json").write_text(
        '{"role":"selected-provider"}', encoding="utf-8"
    )
    (authority.workspace.path / "outside-alias").symlink_to(secret)

    class Relay(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"role-relay-ok")

        @override
        def log_message(self, format: str, *args: object) -> None:
            return

    relay = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Relay)
    serving = threading.Thread(target=relay.serve_forever, daemon=True)
    serving.start()
    script = authority.workspace.path / "probe.js"
    paths = {
        "private": str(secret),
        "alias": str(authority.workspace.path / "outside-alias"),
        "other_role": str(other_home / "auth.json"),
        "host_process_root": f"/proc/{os.getpid()}/root{secret}",
    }
    script.write_text(
        """
const fs = require('fs'), cp = require('child_process'), http = require('http');
const out = {};
for (const [key, path] of Object.entries(PRIVATE_PATHS)) {
  try { fs.readFileSync(path); out[key] = 'permitted'; } catch(e) { out[key] = e.code; }
}
out.auth = JSON.parse(fs.readFileSync(process.env.HOME + '/auth.json')).role;
fs.writeFileSync('project-write', 'permitted');
const child = cp.spawnSync(
  process.execPath, ['-e', 'process.exit(13)'], {timeout:5000});
out.child_exit = child.status;
try {
  fs.writeFileSync(process.execPath, 'overwrite'); out.runtime_write = 'permitted';
}
catch(e) { out.runtime_write = e.code; }
out.leaked_env = CONTROL_NAMES.filter(name => name in process.env);
out.actor = process.env.VAULTSPEC_A2A_AUTHORING_ACTOR_TOKEN === 'synthetic-role';
out.inherited_directory_grants = [];
for (const fd of fs.readdirSync('/proc/self/fd')) {
  try {
    const target = fs.readlinkSync('/proc/self/fd/' + fd);
    if (GRANT_PATHS.includes(target)) out.inherited_directory_grants.push(target);
  } catch(e) {}
}
const request = http.get('http://127.0.0.1:PORT/', response => {
  out.loopback = response.statusCode; response.resume();
  response.on('end', () => console.log(JSON.stringify(out)));
});
request.setTimeout(3000, () => request.destroy());
request.on('error', e => { out.loopback = e.code; console.log(JSON.stringify(out)); });
""".replace("PRIVATE_PATHS", json.dumps(paths))
        .replace(
            "CONTROL_NAMES",
            json.dumps(
                [
                    "VAULTSPEC_A2A_GATEWAY_TOKEN",
                    "VAULTSPEC_A2A_INTERNAL_TOKEN",
                    "DATABASE_URL",
                    "gateway_token",
                    "VAULTSPEC_A2A_AUTHORING_BEARER",
                    "VAULTSPEC_A2A_AUTHORING_BASE_URL",
                ]
            ),
        )
        .replace(
            "GRANT_PATHS",
            json.dumps(
                [
                    str(authority.capsule.path),
                    str(authority.workspace.path),
                    str(authority.home.path),
                    str(private),
                ]
            ),
        )
        .replace("PORT", str(relay.server_port)),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "VAULTSPEC_A2A_GATEWAY_TOKEN": "synthetic-gateway",
        "VAULTSPEC_A2A_INTERNAL_TOKEN": "synthetic-worker",
        "DATABASE_URL": "synthetic-database",
        "gateway_token": "synthetic-alias",
        "VAULTSPEC_A2A_AUTHORING_BEARER": "synthetic-engine",
        "VAULTSPEC_A2A_AUTHORING_BASE_URL": "http://127.0.0.1:1",
        "VAULTSPEC_A2A_AUTHORING_ACTOR_TOKEN": "synthetic-role",
    }
    descriptor = os.open(private, os.O_RDONLY | os.O_DIRECTORY)
    try:
        completed = subprocess.run(
            linux_isolated_command(
                authority, [str(node), str(script)], cwd=str(authority.workspace.path)
            ),
            env=env,
            pass_fds=(descriptor,),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        observed = json.loads(completed.stdout)
        assert all(observed[key] == "ENOENT" for key in paths)
        assert observed["auth"] == "selected-provider"
        assert observed["child_exit"] == 13
        assert observed["runtime_write"] == "EROFS"
        assert observed["loopback"] == 200
        assert observed["leaked_env"] == []
        assert observed["inherited_directory_grants"] == []
        assert observed["actor"] is True
        assert (authority.workspace.path / "project-write").read_text() == "permitted"
    finally:
        os.close(descriptor)
        relay.shutdown()
        relay.server_close()
        serving.join(3)


def test_changed_helper_is_refused_before_provider_work(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    if sys.platform != "linux":
        with pytest.raises(ProcessContainmentError, match="requires Linux"):
            linux_isolated_command(authority, [sys.executable], cwd=str(tmp_path))
        return
    node = _install_runtime(authority)
    helper = authority.capsule.path / "isolation" / "bin" / "bubblewrap"
    with helper.open("r+b") as stream:
        stream.write(b"changed-helper")
    marker = authority.workspace.path / "started"
    completed = subprocess.run(
        linux_isolated_command(
            authority,
            [str(node), "-e", "require('fs').writeFileSync('started','unsafe')"],
            cwd=str(authority.workspace.path),
        ),
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode != 0
    assert "differs from its pinned closure" in completed.stderr
    assert not marker.exists()
