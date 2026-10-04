"""Qualify a committed production worker image without workspace build inputs."""

from __future__ import annotations

import argparse
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> str:
    """Execute a bounded command and preserve failures for CI."""
    return subprocess.run(
        args, cwd=ROOT, check=True, text=True, stdout=subprocess.PIPE, timeout=3600
    ).stdout.strip()


def qualify(ref: str) -> None:
    """Build an archived revision and prove isolation in a disposable container."""
    revision = run("git", "rev-parse", "--verify", f"{ref}^{{commit}}")
    with tempfile.TemporaryDirectory(prefix="worker-qualification-") as temporary:
        directory = Path(temporary)
        archive = directory / "source.tar"
        run("git", "archive", "--format=tar", f"--output={archive}", revision)
        source = directory / "source"
        source.mkdir()
        with tarfile.open(archive) as bundle:
            bundle.extractall(source, filter="data")
        image_file = directory / "image-id"
        run(
            "docker",
            "build",
            "--target",
            "worker",
            "--iidfile",
            str(image_file),
            "--label",
            f"org.opencontainers.image.revision={revision}",
            "--file",
            str(source / "service/docker/prod.Dockerfile"),
            str(source),
        )
        image = image_file.read_text().strip()
        container = ""
        try:
            container = run(
                "docker",
                "create",
                "--user",
                "0",
                "--entrypoint",
                "/app/.venv/bin/python",
                image,
                "/tmp/mcp_probe_isolation.py",
            )
            run(
                "docker",
                "cp",
                str(source / "dev/audit/mcp_probe_isolation.py"),
                f"{container}:/tmp/mcp_probe_isolation.py",
            )
            print(run("docker", "start", "--attach", container), flush=True)
            exit_code = run(
                "docker", "inspect", "--format", "{{.State.ExitCode}}", container
            )
            if exit_code != "0":
                raise RuntimeError(f"Worker isolation proof exited {exit_code}")
        finally:
            if container:
                run("docker", "rm", "--force", container)
        print(f"Qualified worker {image} from {revision}", flush=True)


def main() -> None:
    """Expose the qualification recipe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()
    qualify(args.ref)


if __name__ == "__main__":
    main()
