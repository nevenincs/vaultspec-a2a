"""Publish same-source service images and their immutable deployment receipt."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import cast

from dev.container_release import qualify, run

RECEIPT = "container-release.json"
ROLES = ("gateway", "worker")


def release_identity(tag: str, repository: str) -> str:
    """Validate external names before using them as Git or registry arguments."""
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Expected a stable vMAJOR.MINOR.PATCH release tag")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected owner/repository")
    return f"ghcr.io/{repository.lower()}"


def validate_receipt(value: object, tag: str, repository: str) -> dict[str, str]:
    """Reject foreign, mutable, incomplete or malformed image references."""
    prefix = release_identity(tag, repository)
    if not isinstance(value, dict):
        raise ValueError("Unsupported container receipt")
    record = cast("dict[object, object]", value)
    if record.get("schema") != 1:
        raise ValueError("Unsupported container receipt")
    if record.get("tag") != tag or record.get("repository") != repository:
        raise ValueError("Receipt does not belong to the requested release")
    if record.get("platform") != "linux/amd64":
        raise ValueError("Unsupported deployment platform")
    revision = record.get("revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid source revision")
    images = record.get("images")
    if not isinstance(images, dict):
        raise ValueError("Receipt must contain exactly gateway and worker")
    image_records = cast("dict[object, object]", images)
    if set(image_records) != set(ROLES):
        raise ValueError("Receipt must contain exactly gateway and worker")
    result: dict[str, str] = {}
    for role in ROLES:
        image = image_records[role]
        if not isinstance(image, str) or not re.fullmatch(
            re.escape(f"{prefix}-{role}@sha256:") + r"[0-9a-f]{64}", image
        ):
            raise ValueError(f"Invalid immutable {role} image")
        result[role] = image
    return result


def publish(tag: str, repository: str, destination: Path) -> None:
    """Push qualified image bytes using a short-lived isolated Docker login."""
    prefix = release_identity(tag, repository)
    draft = run(
        "gh",
        "release",
        "view",
        tag,
        "--repo",
        repository,
        "--json",
        "isDraft",
        "--jq",
        ".isDraft",
    )
    if draft != "true":
        raise ValueError("Images can only be attached to an existing draft release")
    revision = run("git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    worker = qualify(revision)
    # storage-anchor-ok: disposable build inputs and credentials, removed on exit.
    with tempfile.TemporaryDirectory(  # storage-anchor-ok
        prefix="container-publish-"
    ) as temporary:
        directory = Path(temporary)
        archive = directory / "source.tar"
        run("git", "archive", "--format=tar", f"--output={archive}", revision)
        source = directory / "source"
        source.mkdir()
        with tarfile.open(archive) as bundle:
            bundle.extractall(source, filter="data")
        image_file = directory / "gateway-id"
        run(
            "docker",
            "build",
            "--target",
            "gateway",
            "--iidfile",
            str(image_file),
            "--label",
            f"org.opencontainers.image.revision={revision}",
            "--label",
            f"org.opencontainers.image.source=https://github.com/{repository}",
            "--file",
            str(source / "service/docker/prod.Dockerfile"),
            str(source),
        )
        config = directory / "docker"
        config.mkdir(mode=0o700)
        docker = ("docker", "--config", str(config))
        subprocess.run(
            [
                *docker,
                "login",
                "ghcr.io",
                "--username",
                os.environ["GITHUB_ACTOR"],
                "--password-stdin",
            ],
            input=os.environ["GH_TOKEN"],
            text=True,
            check=True,
            capture_output=True,
            timeout=60,
        )
        images: dict[str, str] = {}
        for role, image in (
            ("gateway", image_file.read_text().strip()),
            ("worker", worker),
        ):
            name = f"{prefix}-{role}"
            run_id = os.environ["GITHUB_RUN_ID"]
            attempt = os.environ["GITHUB_RUN_ATTEMPT"]
            candidate = f"{name}:build-{run_id}-{attempt}"
            run(*docker, "tag", image, candidate)
            run(*docker, "push", candidate)
            digests = json.loads(
                run(*docker, "inspect", "--format", "{{json .RepoDigests}}", candidate)
            )
            images[role] = next(
                item for item in digests if item.startswith(name + "@sha256:")
            )
        receipt = {
            "schema": 1,
            "tag": tag,
            "repository": repository,
            "revision": revision,
            "platform": "linux/amd64",
            "images": images,
        }
        validate_receipt(receipt, tag, repository)
        destination.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Publish from workflow environment values, never shell interpolation."""
    publish(os.environ["RELEASE_TAG"], os.environ["GITHUB_REPOSITORY"], Path(RECEIPT))


if __name__ == "__main__":
    main()
