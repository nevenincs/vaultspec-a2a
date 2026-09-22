"""Prepare reviewable release metadata without creating or publishing a release."""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROJECT_VERSION = re.compile(r'(?m)^(version = ")([^"]+)("\s*)$')
LOCK_PACKAGE = re.compile(
    r'(?ms)(\[\[package\]\]\s*\nname = "vaultspec-a2a"\s*\nversion = ")([^"]+)(")'
)
CHANGELOG_MARKER = "<!-- prepared releases are inserted below this line -->"


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> Version:
        match = SEMVER.fullmatch(value)
        if match is None:
            raise ValueError(f"invalid version {value!r}; expected MAJOR.MINOR.PATCH")
        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def git(*args: str, root: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return result.stdout


def reachable_versions(root: Path) -> list[tuple[Version, str]]:
    tags = git("tag", "--merged", "HEAD", "--list", "v*", root=root).splitlines()
    versions: list[tuple[Version, str]] = []
    for tag in tags:
        try:
            versions.append((Version.parse(tag.removeprefix("v")), tag))
        except ValueError:
            continue
    return sorted(versions)


def replace_one(pattern: re.Pattern[str], text: str, version: str, path: Path) -> str:
    updated, count = pattern.subn(rf"\g<1>{version}\g<3>", text, count=1)
    if count != 1:
        raise ValueError(f"expected exactly one project version in {path}")
    return updated


def changelog_entry(root: Path, version: str, release_date: str, base_tag: str) -> str:
    head = git("rev-parse", "HEAD", root=root).strip()
    records = git(
        "log",
        "--no-merges",
        "--format=%s",
        f"{base_tag}..HEAD",
        root=root,
    ).splitlines()
    records = [line for line in records if not line.startswith("chore(release):")]
    if not records:
        raise ValueError(f"no non-release commits found after reachable tag {base_tag}")

    groups: dict[str, list[str]] = {
        "Breaking": [],
        "Features": [],
        "Fixes": [],
        "Other": [],
    }
    for subject in records:
        lowered = subject.lower()
        if "!:" in subject or "breaking change" in lowered:
            group = "Breaking"
        elif re.match(r"^feat(?:\([^)]*\))?:", subject):
            group = "Features"
        elif re.match(r"^fix(?:\([^)]*\))?:", subject):
            group = "Fixes"
        else:
            group = "Other"
        groups[group].append(subject)

    lines = [
        f"## [{version}] - {release_date}",
        "",
        f"Changes from reachable tag `{base_tag}` through commit `{head}`.",
        "",
    ]
    for heading, subjects in groups.items():
        if subjects:
            lines.extend(
                (f"### {heading}", "", *(f"- {subject}" for subject in subjects), "")
            )
    return "\n".join(lines).rstrip() + "\n\n"


def prepare(root: Path, target: Version, release_date: str) -> dict[Path, str]:
    if ISO_DATE.fullmatch(release_date) is None:
        raise ValueError(f"invalid release date {release_date!r}; expected YYYY-MM-DD")
    date.fromisoformat(release_date)
    pyproject = root / "pyproject.toml"
    lockfile = root / "uv.lock"
    changelog = root / "CHANGELOG.md"
    pyproject_text = pyproject.read_text(encoding="utf-8")
    lock_text = lockfile.read_text(encoding="utf-8")
    current_match = PROJECT_VERSION.search(pyproject_text)
    lock_match = LOCK_PACKAGE.search(lock_text)
    if current_match is None or lock_match is None:
        raise ValueError("project version is missing from pyproject.toml or uv.lock")
    current = Version.parse(current_match.group(2))
    if lock_match.group(2) != str(current):
        raise ValueError(
            "pyproject.toml and the editable vaultspec-a2a package in uv.lock disagree"
        )
    tags = reachable_versions(root)
    if not tags:
        raise ValueError("no reachable semantic vMAJOR.MINOR.PATCH tag found")
    latest, base_tag = tags[-1]
    changelog_text = changelog.read_text(encoding="utf-8")
    target_heading = re.search(
        rf"(?m)^## \[{re.escape(str(target))}\] - {re.escape(release_date)}$",
        changelog_text,
    )
    if target == current and target_heading is not None:
        head = git("rev-parse", "HEAD", root=root).strip()
        attribution = (
            f"Changes from reachable tag `{base_tag}` through commit `{head}`."
        )
        if target <= latest or attribution not in changelog_text:
            raise ValueError(
                "prepared changelog does not match the current reachable tag range"
            )
        return {
            pyproject: pyproject_text,
            lockfile: lock_text,
            changelog: changelog_text,
        }
    if current != latest:
        raise ValueError(
            f"project version {current} does not match latest reachable tag {base_tag}"
        )
    floor = current
    if target <= floor:
        raise ValueError(
            f"target {target} must be greater than current/reachable version {floor}"
        )

    if CHANGELOG_MARKER not in changelog_text:
        raise ValueError(f"{changelog} is missing its insertion marker")
    if re.search(rf"(?m)^## \[{re.escape(str(target))}\] ", changelog_text):
        raise ValueError(f"CHANGELOG.md already contains {target}")
    entry = changelog_entry(root, str(target), release_date, base_tag)
    return {
        pyproject: replace_one(PROJECT_VERSION, pyproject_text, str(target), pyproject),
        lockfile: replace_one(LOCK_PACKAGE, lock_text, str(target), lockfile),
        changelog: changelog_text.replace(
            CHANGELOG_MARKER, f"{CHANGELOG_MARKER}\n\n{entry}", 1
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "version",
        nargs="?",
        help="operator-selected MAJOR.MINOR.PATCH",
    )
    parser.add_argument("--release-date", help="ISO release date (YYYY-MM-DD)")
    parser.add_argument(
        "--from-env",
        action="store_true",
        help="read VERSION and RELEASE_DATE from the process environment",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="fail unless files are already prepared"
    )
    mode.add_argument(
        "--dry-run", action="store_true", help="print the patch without writing"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.from_env:
        if args.version is not None or args.release_date is not None:
            parser.error("--from-env cannot be combined with version arguments")
    elif args.version is None or args.release_date is None:
        parser.error(
            "version and --release-date are required unless --from-env is used"
        )
    return args


def release_inputs(args: argparse.Namespace) -> tuple[str, str]:
    if not args.from_env:
        return args.version, args.release_date

    version = os.environ.get("VERSION")
    release_date = os.environ.get("RELEASE_DATE")
    missing = [
        name
        for name, value in (("VERSION", version), ("RELEASE_DATE", release_date))
        if value is None
    ]
    if missing:
        raise ValueError(f"missing environment variable(s): {', '.join(missing)}")
    if not isinstance(version, str) or not isinstance(release_date, str):
        raise ValueError("release environment variables must be strings")
    return version, release_date


def main() -> int:
    args = parse_args()
    try:
        version, release_date = release_inputs(args)
        outputs = prepare(args.root.resolve(), Version.parse(version), release_date)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"prepare-release: {exc}", file=sys.stderr)
        return 2

    changed = []
    for path, updated in outputs.items():
        original = path.read_text(encoding="utf-8")
        if original == updated:
            continue
        changed.append(path)
        if args.dry_run or args.check:
            print(
                "".join(
                    difflib.unified_diff(
                        original.splitlines(keepends=True),
                        updated.splitlines(keepends=True),
                        fromfile=str(path),
                        tofile=str(path),
                    )
                ),
                end="",
            )
        else:
            path.write_text(updated, encoding="utf-8", newline="\n")
    if args.check and changed:
        print("prepare-release: metadata is not prepared", file=sys.stderr)
        return 1
    action = "checked" if args.check else "previewed" if args.dry_run else "prepared"
    print(f"prepare-release: {action} {version} ({len(changed)} file(s) changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
