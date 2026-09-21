from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT = Path(__file__).parents[1] / "prepare_release.py"
ROOT = SCRIPT.parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def git_bash() -> Path:
    exec_path = Path(
        subprocess.run(
            ["git", "--exec-path"], check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    candidate = exec_path.parents[2] / "bin" / "bash.exe"
    return candidate if candidate.is_file() else Path("bash")


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*args], cwd=cwd, check=check, capture_output=True, text=True)


def git(repo: Path, *args: str) -> None:
    run("git", *args, cwd=repo)


def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    git(repo, "config", "user.name", "Release Fixture")
    git(repo, "config", "user.email", "release@example.invalid")
    (repo / "scripts").mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "vaultspec-a2a"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    (repo / "uv.lock").write_text(
        '[[package]]\nname = "vaultspec-a2a"\nversion = "1.2.3"\n'
        'source = { editable = "." }\n',
        encoding="utf-8",
    )
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n<!-- prepared releases are inserted below this line -->\n",
        encoding="utf-8",
    )
    (repo / "scripts" / "prepare_release.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from scripts.prepare_release import main\n"
        "raise SystemExit(main())\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "chore: fixture baseline")
    git(repo, "tag", "v1.2.3")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    git(repo, "add", "feature.txt")
    git(repo, "commit", "-m", "feat(core): add deterministic preparation")
    (repo / "fix.txt").write_text("fix\n", encoding="utf-8")
    git(repo, "add", "fix.txt")
    git(repo, "commit", "-m", "fix: preserve release authority")
    return repo


def workflow_script(step_name: str, job: str = "build") -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in workflow["jobs"][job]["steps"]:
        if step.get("name") == step_name:
            return str(step["run"])
    raise AssertionError(f"workflow step not found: {step_name}")


def run_version_gate(
    repo: Path, raw_tag: str, event_ref: str, manual_tag: str = ""
) -> subprocess.CompletedProcess[str]:
    output = repo / "github-output"
    env = os.environ.copy()
    env.update(
        {
            "RAW_TAG": raw_tag,
            "MANUAL_TAG": manual_tag,
            "EVENT_REF": event_ref,
            "PY": sys.executable,
            "GITHUB_OUTPUT": str(output),
        }
    )
    return subprocess.run(
        [str(git_bash()), "-c", workflow_script("Resolve and agree the version")],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=15,
    )


def run_prepare_recipe(
    repo: Path, *, version: str, release_date: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({"VERSION": version, "RELEASE_DATE": release_date})
    return subprocess.run(
        [
            "just",
            "--justfile",
            str(ROOT / "Justfile"),
            "--working-directory",
            str(repo),
            "prepare-release",
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_prepare_and_check_are_replayable(tmp_path: Path) -> None:
    repo = fixture_repo(tmp_path)
    command = (
        sys.executable,
        str(SCRIPT),
        "1.3.0",
        "--release-date",
        "2026-09-21",
        "--root",
        str(repo),
    )
    first = run(*command, cwd=repo)
    assert "3 file(s) changed" in first.stdout
    assert 'version = "1.3.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "1.3.0"' in (repo / "uv.lock").read_text(encoding="utf-8")
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Changes from reachable tag `v1.2.3` through commit `" in changelog
    assert "### Features" in changelog
    assert "### Fixes" in changelog

    checked = run(*command, "--check", cwd=repo)
    assert "0 file(s) changed" in checked.stdout


def test_prepare_recipe_reads_valid_environment_on_native_shell(tmp_path: Path) -> None:
    repo = fixture_repo(tmp_path)

    result = run_prepare_recipe(repo, version="1.3.0", release_date="2026-09-21")

    assert result.returncode == 0, result.stderr
    assert 'version = "1.3.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "1.3.0"' in (repo / "uv.lock").read_text(encoding="utf-8")
    assert "## [1.3.0] - 2026-09-21" in (repo / "CHANGELOG.md").read_text(
        encoding="utf-8"
    )


def test_refuses_nonmonotonic_version_without_writes(tmp_path: Path) -> None:
    repo = fixture_repo(tmp_path)
    before = {
        path: (repo / path).read_bytes()
        for path in ("pyproject.toml", "uv.lock", "CHANGELOG.md")
    }
    result = run(
        sys.executable,
        str(SCRIPT),
        "1.2.3",
        "--release-date",
        "2026-09-21",
        "--root",
        str(repo),
        cwd=repo,
        check=False,
    )
    assert result.returncode == 2
    assert "must be greater" in result.stderr
    assert before == {path: (repo / path).read_bytes() for path in before}


def test_dry_run_uses_only_reachable_semantic_tags(tmp_path: Path) -> None:
    repo = fixture_repo(tmp_path)
    git(repo, "tag", "not-a-release")
    git(repo, "tag", "v9.0.0", "HEAD~1")
    unreachable = run(
        "git", "commit-tree", "HEAD^{tree}", "-m", "unreachable release", cwd=repo
    ).stdout.strip()
    git(repo, "tag", "v99.0.0", unreachable)
    for path in (repo / "pyproject.toml", repo / "uv.lock"):
        path.write_text(
            path.read_text(encoding="utf-8").replace("1.2.3", "9.0.0"),
            encoding="utf-8",
        )
    before = (repo / "pyproject.toml").read_bytes()
    result = run(
        sys.executable,
        str(SCRIPT),
        "9.1.0",
        "--release-date",
        "2026-09-21",
        "--dry-run",
        "--root",
        str(repo),
        cwd=repo,
    )
    assert "Changes from reachable tag `v9.0.0` through commit `" in result.stdout
    assert (repo / "pyproject.toml").read_bytes() == before


def test_release_gate_accepts_only_an_exact_tag_at_head(tmp_path: Path) -> None:
    repo = fixture_repo(tmp_path)
    git(repo, "tag", "--force", "v1.2.3", "HEAD")

    result = run_version_gate(repo, "v1.2.3", "refs/tags/v1.2.3")

    assert result.returncode == 0, result.stderr
    assert (repo / "github-output").read_text(encoding="utf-8") == "value=1.2.3\n"


def test_release_gate_rejects_a_branch_spoofing_a_version_tag(tmp_path: Path) -> None:
    repo = fixture_repo(tmp_path)
    git(repo, "tag", "--delete", "v1.2.3")
    git(repo, "branch", "v1.2.3")

    result = run_version_gate(repo, "v1.2.3", "refs/heads/v1.2.3", "v1.2.3")

    assert result.returncode != 0
    assert "release tag does not exist" in result.stderr


def test_release_gate_rejects_tag_not_resolving_to_head(tmp_path: Path) -> None:
    repo = fixture_repo(tmp_path)

    result = run_version_gate(repo, "v1.2.3", "refs/tags/v1.2.3")

    assert result.returncode != 0
    assert "does not resolve to checked-out HEAD" in result.stderr


def test_untrusted_release_inputs_remain_data_at_command_boundaries(
    tmp_path: Path,
) -> None:
    repo = fixture_repo(tmp_path)
    marker = repo / "injected"
    malicious = f"1.3.0 & echo injected > {marker}"

    tag_result = run_version_gate(repo, f"v{malicious}", "refs/tags/v1.2.3", malicious)
    before = {
        path: (repo / path).read_bytes()
        for path in ("pyproject.toml", "uv.lock", "CHANGELOG.md")
    }
    recipe_result = run_prepare_recipe(
        repo, version=malicious, release_date="2026-09-21"
    )

    assert tag_result.returncode != 0
    assert "strict vMAJOR.MINOR.PATCH" in tag_result.stderr
    assert recipe_result.returncode != 0
    assert "invalid version" in recipe_result.stderr
    assert before == {path: (repo / path).read_bytes() for path in before}
    assert not marker.exists()


def test_malicious_release_date_remains_data_at_recipe_boundary(
    tmp_path: Path,
) -> None:
    repo = fixture_repo(tmp_path)
    marker = repo / "injected-date"
    before = {
        path: (repo / path).read_bytes()
        for path in ("pyproject.toml", "uv.lock", "CHANGELOG.md")
    }

    result = run_prepare_recipe(
        repo,
        version="1.3.0",
        release_date=f"2026-09-21 & echo injected > {marker}",
    )

    assert result.returncode != 0
    assert "invalid release date" in result.stderr
    assert before == {path: (repo / path).read_bytes() for path in before}
    assert not marker.exists()


def test_release_cohort_rejects_stale_members_on_a_persistent_runner(
    tmp_path: Path,
) -> None:
    members = tmp_path / "release-members-123-1"
    members.mkdir()
    version = "1.2.3"
    for target, extension in (
        ("x86_64-unknown-linux-gnu", "tar.gz"),
        ("aarch64-unknown-linux-gnu", "tar.gz"),
        ("aarch64-apple-darwin", "tar.gz"),
        ("x86_64-pc-windows-msvc", "zip"),
    ):
        archive = members / f"vaultspec-a2a-{version}-{target}.{extension}"
        archive.write_bytes(b"archive")
        archive.with_name(f"{archive.name}.sha256").write_text(
            "0" * 64, encoding="ascii"
        )

    env = os.environ.copy()
    env.update({"RAW_TAG": f"v{version}", "MEMBERS_DIR": str(members)})
    command = [
        str(git_bash()),
        "-c",
        workflow_script("Refuse an incomplete cohort", job="publish"),
    ]
    accepted = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=15,
    )
    (members / "stale-secret.txt").write_text("must not upload", encoding="utf-8")
    rejected = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=15,
    )

    assert accepted.returncode == 0, accepted.stderr
    assert rejected.returncode != 0
    assert "unexpected members" in rejected.stderr
