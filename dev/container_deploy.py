"""Promote a signed container receipt on an explicitly configured Compose host."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from dev.container_publish import RECEIPT, release_identity, validate_receipt
from dev.container_release import run


def host_configuration() -> tuple[Path, Path, str]:
    """Require explicit host paths and project identity before any mutation."""
    root = Path(os.environ["A2A_DEPLOY_ROOT"])
    env_file = Path(os.environ["A2A_DEPLOY_ENV_FILE"])
    project = os.environ["A2A_COMPOSE_PROJECT"]
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("A2A_DEPLOY_ROOT must be an existing absolute directory")
    if not env_file.is_absolute() or not env_file.is_file():
        raise ValueError("A2A_DEPLOY_ENV_FILE must name an existing absolute file")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
        raise ValueError("Set the exact existing Compose project name")
    return root, env_file, project


def fetch_receipt(directory: Path, tag: str, repository: str) -> dict[str, str]:
    """Verify release visibility, signature and tag binding before image access."""
    release_identity(tag, repository)
    state = json.loads(
        run(
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            repository,
            "--json",
            "isDraft,isPrerelease",
        )
    )
    if state["isDraft"] or state["isPrerelease"]:
        raise ValueError("Only published stable releases can be deployed")
    run(
        "gh",
        "release",
        "download",
        tag,
        "--repo",
        repository,
        "--pattern",
        RECEIPT,
        "--dir",
        str(directory),
    )
    receipt = directory / RECEIPT
    run(
        "gh",
        "attestation",
        "verify",
        str(receipt),
        "--repo",
        repository,
        "--signer-workflow",
        f"{repository}/.github/workflows/release.yml",
        "--source-ref",
        "refs/heads/main",
    )
    document = json.loads(receipt.read_text(encoding="utf-8"))
    images = validate_receipt(document, tag, repository)
    revision = run("git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    if document["revision"] != revision:
        raise ValueError("Release tag has moved since image publication")
    for filename in ("docker-compose.prod.yml", "docker-compose.release.yml"):
        (directory / filename).write_text(
            run("git", "show", f"{revision}:service/{filename}"), encoding="utf-8"
        )
    return images


def verify_services(compose: tuple[str, ...], images: dict[str, str]) -> None:
    """Require exact running image identities and gateway-worker registration."""
    for role, expected in images.items():
        container = run(*compose, "ps", "--quiet", role)
        actual = run("docker", "inspect", "--format", "{{.Config.Image}}", container)
        if actual != expected:
            raise RuntimeError(f"Running {role} image differs from the release receipt")
    probe = (
        "import json,time,urllib.request; deadline=time.monotonic()+120\n"
        "while time.monotonic()<deadline:\n"
        " try:\n"
        "  with urllib.request.urlopen('http://localhost:18000/health',timeout=5) "
        "as r:\n"
        "   if json.load(r).get('worker_connected') is True: break\n"
        " except (OSError,ValueError): pass\n"
        " time.sleep(2)\n"
        "else: raise SystemExit('Gateway did not register the worker')\n"
    )
    run(*compose, "exec", "--no-TTY", "gateway", "python", "-c", probe)


def deploy(tag: str, repository: str) -> None:
    """Pull verified digests, reconcile Compose and persist successful promotion."""
    root, env_file, project = host_configuration()
    # storage-anchor-ok: disposable release receipt and registry login, not state.
    with tempfile.TemporaryDirectory(  # storage-anchor-ok
        prefix="promotion-"
    ) as temporary:
        directory = Path(temporary)
        images = fetch_receipt(directory, tag, repository)
        config = directory / "docker"
        config.mkdir(mode=0o700)
        subprocess.run(
            [
                "docker",
                "--config",
                str(config),
                "login",
                "ghcr.io",
                "--username",
                os.environ["GITHUB_ACTOR"],
                "--password-stdin",
            ],
            input=os.environ["GH_TOKEN"],
            text=True,
            capture_output=True,
            check=True,
            timeout=60,
        )
        compose = (
            "docker",
            "--config",
            str(config),
            "compose",
            "--project-name",
            project,
            "--project-directory",
            str(root),
            "--env-file",
            str(env_file),
            "--file",
            str(directory / "docker-compose.prod.yml"),
        )
        overlay = os.environ.get("A2A_DEPLOY_COMPOSE_OVERRIDE", "")
        if overlay:
            path = Path(overlay)
            if not path.is_absolute() or not path.is_file():
                raise ValueError("Compose override must be an existing absolute file")
            compose += ("--file", str(path))
        compose += ("--file", str(directory / "docker-compose.release.yml"))
        os.environ["A2A_GATEWAY_IMAGE"] = images["gateway"]
        os.environ["A2A_WORKER_IMAGE"] = images["worker"]
        run(*compose, "config", "--quiet")
        run(*compose, "pull")
        run(*compose, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "180")
        verify_services(compose, images)
        current = root / RECEIPT
        if current.exists():
            (root / "container-release.previous.json").write_bytes(current.read_bytes())
        pending = root / "container-release.pending.json"
        pending.write_bytes((directory / RECEIPT).read_bytes())
        pending.replace(current)
        print(f"Promoted {tag} to Compose project {project}", flush=True)


if __name__ == "__main__":
    deploy(os.environ["RELEASE_TAG"], os.environ["GITHUB_REPOSITORY"])
