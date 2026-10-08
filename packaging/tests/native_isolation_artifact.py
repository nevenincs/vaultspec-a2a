"""Explicit artifact checks; invoke after building the actual Linux onedir.

Required inputs: VAULTSPEC_A2A_TEST_FROZEN_RUNTIME_TREE and
VAULTSPEC_A2A_TEST_LINUX_NODE. The staged manifest must include the latter's
declared ELF dependencies. These controls do not qualify provider authentication.
"""

from __future__ import annotations

import json
import os
import runpy
import shutil
import ssl
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest

from vaultspec_a2a.desktop.native_isolation import (
    NativeLaunchAuthority,
    linux_isolated_launch,
)
from vaultspec_a2a.desktop.profile import derive_state_paths
from vaultspec_a2a.testing import LivenessWatch, ProgressDeadline, wait_until
from vaultspec_a2a.utils import ProcessContainment, reap_contained, spawn_contained

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.parametrize(
    "mutation", ["valid", "missing", "empty", "symlink", "hardlink", "oversized"]
)
def test_certificate_build_input_requires_the_frozen_regular_bundle(
    tmp_path: Path, mutation: str
) -> None:
    producer = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/build_linux_isolation.py")
    )
    select = cast("Callable[[Path], Path]", producer["certificate_bundle"])
    bundle = tmp_path / "_internal/certifi/cacert.pem"
    bundle.parent.mkdir(parents=True)
    source = (
        Path(os.environ["VAULTSPEC_A2A_TEST_FROZEN_RUNTIME_TREE"])
        / "_internal/certifi/cacert.pem"
    )
    if mutation == "missing":
        with pytest.raises(FileNotFoundError):
            select(tmp_path)
        return
    if mutation == "empty":
        bundle.write_bytes(b"")
    elif mutation == "oversized":
        bundle.write_bytes(b"\n" * (1024 * 1024 + 1))
    elif mutation == "symlink":
        alternate = tmp_path / "alternate.pem"
        shutil.copyfile(source, alternate)
        bundle.symlink_to(alternate)
    else:
        shutil.copyfile(source, bundle)
        if mutation == "hardlink":
            (tmp_path / "alternate.pem").hardlink_to(bundle)
    if mutation == "valid":
        assert select(tmp_path) == bundle
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=str(bundle))
        assert context.cert_store_stats()["x509_ca"] > 0
    else:
        with pytest.raises(ValueError, match="bounded regular file"):
            select(tmp_path)


def _artifact(tmp_path: Path) -> tuple[NativeLaunchAuthority, Path, Path]:
    app_home = tmp_path / "app"
    capsule = tmp_path / "capsule"
    state = derive_state_paths(app_home)
    project = state.workspaces_root / "project"
    home = state.temp_homes_dir / "artifact-role"
    project.mkdir(parents=True)
    home.mkdir(parents=True)
    capsule.mkdir()
    authority = NativeLaunchAuthority.issue(
        app_home=app_home, capsule=capsule, workspace=project, home=home
    )
    tree = Path(os.environ["VAULTSPEC_A2A_TEST_FROZEN_RUNTIME_TREE"])
    component = authority.capsule.path / "a2a"
    shutil.copytree(tree, component)
    source = Path(os.environ["VAULTSPEC_A2A_TEST_LINUX_NODE"])
    node = authority.capsule.path / "node/bin/node"
    node.parent.mkdir(parents=True)
    shutil.copyfile(source, node)
    node.chmod(source.stat().st_mode & 0o777)
    return authority, component / "vaultspec-a2a", node


def _run(
    authority: NativeLaunchAuthority, binary: Path, command: list[str]
) -> subprocess.CompletedProcess[str]:
    launch = linux_isolated_launch(
        authority, command, cwd=str(authority.workspace.path), environment={}
    )
    return subprocess.run(
        [
            str(binary),
            "run-module",
            "vaultspec_a2a.desktop._linux_launcher",
            authority.encode(),
            str(authority.workspace.path),
            *command,
        ],
        cwd=launch.cwd,
        env=dict(launch.environment),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_frozen_component_preserves_work_and_denies_private_state(
    tmp_path: Path,
) -> None:
    authority, binary, node = _artifact(tmp_path)
    private = authority.app_home.path / "private-state"
    private.write_text("synthetic-service-state", encoding="utf-8")
    alias = authority.workspace.path / "outside-alias"
    alias.symlink_to(private)
    (authority.home.path / "auth.json").write_text("selected-synthetic-role")
    script = (
        "const fs=require('fs'), cp=require('child_process');"
        + f"const paths={json.dumps([str(private), str(alias)])};"
        + "const denied=paths.every(p=>{try{fs.readFileSync(p);return false}"
        + "catch(e){return e.code==='ENOENT'}});"
        + "fs.writeFileSync('artifact-project-write','owned');"
        + "const selected=fs.readFileSync(process.env.HOME+'/auth.json','utf8');"
        + "let readonly=false;try{fs.writeFileSync(process.execPath,'changed')}"
        + "catch(e){readonly=e.code==='EROFS'};"
        + "const child=cp.spawnSync(process.execPath,['-e','process.exit(13)']);"
        + "console.log(JSON.stringify({denied,selected,readonly,child:child.status}));"
    )
    result = _run(authority, binary, [str(node), "-e", script])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "denied": True,
        "selected": "selected-synthetic-role",
        "readonly": True,
        "child": 13,
    }
    assert (authority.workspace.path / "artifact-project-write").read_text() == "owned"
    assert private.read_text() == "synthetic-service-state"
    # The genuine frozen runtime can re-enter its own dependency closure inside
    # the namespace, rather than borrowing the test interpreter or host Python.
    version = _run(authority, binary, [str(binary), "--version"])
    assert version.returncode == 0, version.stderr
    assert "vaultspec-a2a" in version.stdout.lower()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "helper",
        "source",
        "outside",
        "resolver",
        "resolver-child",
        "etc",
        "certificate",
    ],
)
def test_frozen_component_refuses_invalid_assets_before_target(
    tmp_path: Path, mutation: str
) -> None:
    authority, binary, node = _artifact(tmp_path)
    manifest = binary.parent / "isolation/runtime.json"
    if mutation == "missing":
        manifest.unlink()
    elif mutation == "helper":
        helper = binary.parent / "isolation/bin/bubblewrap"
        with helper.open("r+b") as stream:
            stream.write(b"changed")
    elif mutation == "source":
        record = json.loads(manifest.read_text())
        record["helper"]["source"] = "../isolation/bin/bubblewrap"
        manifest.write_text(json.dumps(record))
    elif mutation == "certificate":
        record = json.loads(manifest.read_text())
        certificate = next(
            item
            for item in record["files"]
            if item["target"] == "/etc/ssl/certs/ca-certificates.crt"
        )
        (binary.parent / certificate["source"]).write_bytes(b"changed")
    elif mutation in {"resolver", "resolver-child", "etc"}:
        record = json.loads(manifest.read_text())
        record["files"][0]["target"] = {
            "resolver": "/etc/resolv.conf",
            "resolver-child": "/etc/resolv.conf/child",
            "etc": "/etc",
        }[mutation]
        manifest.write_text(json.dumps(record))
    else:
        original = Path(os.environ["VAULTSPEC_A2A_TEST_FROZEN_RUNTIME_TREE"])
        binary = original / "vaultspec-a2a"
    result = _run(
        authority,
        binary,
        [str(node), "-e", "require('fs').writeFileSync('must-not-run','failure')"],
    )
    assert result.returncode != 0
    assert not (authority.workspace.path / "must-not-run").exists()


def test_frozen_dns_https_and_resolver_file_boundary(tmp_path: Path) -> None:
    authority, binary, node = _artifact(tmp_path)
    script = """
const fs=require('fs'), dns=require('dns').promises;
const cp=require('child_process'), https=require('https');
(async()=>{
  const lookup=await dns.lookup('nodejs.org');
  const records=await dns.resolve4('nodejs.org');
  const child=cp.spawnSync(process.execPath,['-e',
    "require('dns').lookup('nodejs.org',(e,a)=>process.exit(e||!a?1:0))"],
    {timeout:15000});
  let readonly=false;
  try{fs.writeFileSync('/etc/resolv.conf','changed')}
  catch(e){readonly=e.code==='EROFS'};
  const resolver=fs.readFileSync('/etc/resolv.conf','utf8');
  const certificate=fs.readFileSync('/etc/ssl/certs/ca-certificates.crt');
  let certificateReadonly=false;
  try{fs.writeFileSync('/etc/ssl/certs/ca-certificates.crt','changed')}
  catch(e){certificateReadonly=e.code==='EROFS'};
  const absent=['/etc/passwd','/etc/shadow','/mnt/wsl/resolv.conf',
    '/run/systemd/resolve/resolv.conf'].every(p=>!fs.existsSync(p));
  const leaked=fs.readdirSync('/proc/self/fd').some(fd=>{
    try{return fs.readlinkSync('/proc/self/fd/'+fd).includes('memfd:')}
    catch(e){return false}
  });
  const download=await new Promise((resolve,reject)=>{
    const request=https.get('https://nodejs.org/dist/v26.8.1/SHASUMS256.txt',
      {ca:certificate},response=>{
      let body=''; response.setEncoding('utf8');
      response.on('data',chunk=>{
        body+=chunk;
        if(body.length>65536) request.destroy(new Error('download bound'));
      });
      response.on('end',()=>resolve({status:response.statusCode,
        manifest:body.includes(
          '3e301118d7df53d563b7e96c1617545f26e2f76f9724be668d6cab65c15dda5d  '
          +'node-v26.8.1-linux-x64.tar.xz')}));
    });
    request.on('error',reject);
    request.setTimeout(15000,()=>request.destroy(new Error('https timeout')));
  });
  console.log(JSON.stringify({lookup:!!lookup.address,records:records.length>0,
    child:child.status,readonly,certificateReadonly,
    resolver:resolver.startsWith('nameserver '),
    absent,leaked,...download}));
})().catch(e=>{console.error(e.code||e.message);process.exitCode=1});
"""
    command = [str(node), "-e", script]
    source_launch = linux_isolated_launch(
        authority, command, cwd=str(authority.workspace.path), environment={}
    )
    # Source closure uses the root layout; the relocated artifact uses a2a/.
    shutil.copytree(binary.parent / "isolation", authority.capsule.path / "isolation")
    source = subprocess.run(
        source_launch.command,
        cwd=source_launch.cwd,
        env=dict(source_launch.environment),
        capture_output=True,
        text=True,
        timeout=30,
    )
    frozen = _run(authority, binary, command)
    expected = {
        "lookup": True,
        "records": True,
        "child": 0,
        "readonly": True,
        "certificateReadonly": True,
        "resolver": True,
        "absent": True,
        "leaked": False,
        "status": 200,
        "manifest": True,
    }
    for result in (source, frozen):
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == expected


def test_frozen_owner_death_removes_detached_child(tmp_path: Path) -> None:
    authority, binary, node = _artifact(tmp_path)
    nonce = "frozen-descendant-" + uuid4().hex
    script = authority.workspace.path / "lifetime.js"
    script.write_text(
        "const cp=require('child_process'),fs=require('fs');\n"
        "const child=cp.spawn(process.execPath,\n"
        "['-e','setInterval(()=>{},1000)',process.argv[2]],\n"
        "{detached:true,stdio:'ignore'});\n"
        "fs.writeFileSync('descendant-ready',String(child.pid));\n"
        "setInterval(()=>{},1000);\n",
        encoding="utf-8",
    )
    launch = linux_isolated_launch(
        authority,
        [str(node), str(script), nonce],
        cwd=str(authority.workspace.path),
        environment={},
    )
    containment = ProcessContainment.create()
    owner = spawn_contained(
        [
            str(binary),
            "run-module",
            "vaultspec_a2a.desktop._linux_launcher",
            authority.encode(),
            str(authority.workspace.path),
            str(node),
            str(script),
            nonce,
        ],
        containment,
        cwd=launch.cwd,
        env=dict(launch.environment),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ready = authority.workspace.path / "descendant-ready"

        def _owner_exited() -> str | None:
            code = owner.poll()
            if code is None:
                return None
            return f"exited with code {code} before the descendant was ready"

        wait_until(
            ready.exists,
            deadline=ProgressDeadline(
                idle_window_s=15.0,
                watches=(LivenessWatch(label="frozen owner", verdict=_owner_exited),),
            ),
            interval_s=0.05,
            stalled=lambda: f"the frozen owner never wrote {ready.name}",
        )
        descendants: list[tuple[Path, int]] = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                arguments = (entry / "cmdline").read_bytes().split(b"\0")
                if nonce.encode() in arguments and b"-e" in arguments:
                    descendants.append((entry, entry.stat().st_ino))
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
        assert len(descendants) == 1
        reap_contained(owner, containment)
        path, identity = descendants[0]
        observed = "unread"

        def _descendant_gone() -> bool:
            nonlocal observed
            try:
                if path.stat().st_ino != identity:
                    observed = "pid reused"
                    return True
                observed = (path / "stat").read_text().rsplit(")", 1)[1].split()[0]
            except (FileNotFoundError, ProcessLookupError):
                observed = "gone"
                return True
            return observed == "Z"

        wait_until(
            _descendant_gone,
            deadline=ProgressDeadline(idle_window_s=5.0),
            interval_s=0.05,
            stalled=lambda: (
                "detached child survived its frozen retained owner "
                f"(last state {observed})"
            ),
        )
    finally:
        reap_contained(owner, containment)
