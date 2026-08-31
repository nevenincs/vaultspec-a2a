"""The descriptor confirmation that closes the inspect-then-read window.

A secret is inspected by NAME and then read from a DESCRIPTOR, and between those
two acts the name can be re-pointed at a file the inspection never saw. Two
readers close that window - the desktop credential loader and the discovery
handoff reader - and both now ask one shared confirmation to do it.

The confirmation is worth certifying on its own because the flag that is
supposed to make it unnecessary DOES NOT EXIST HERE. ``O_NOFOLLOW`` is absent on
Windows, so the open cannot refuse a link and the explicit checks carry the
guarantee alone. A test that only asserted "the loader refuses a link" would
pass identically whether that refusal came from the flag or from the checks, and
would keep passing if the checks were removed on a host where the flag works.

So these tests do not merely observe the refusal - they take it apart. Each
explicit step is blinded in turn against a real planted link, and the refusal is
required to survive; then both are blinded together, leaving only the flag, and
the secret is required to come through. The last assertion is the one that
proves the steps are load-bearing rather than decorative.

The blinded arms deliberately re-sequence the open by hand. They are not a
second copy of the reader under test: they measure what the PLATFORM does when a
step is missing, using the real production flags, which is the only way to show
a step is necessary rather than merely present.
"""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING

import pytest

from ...testing.links import plant_link_to_file
from .._platform_acl import (
    confirm_opened_secret,
    harden_credential_path,
    unfollowed_read_flags,
)

if TYPE_CHECKING:
    from pathlib import Path

_SECRET = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def planted(tmp_path: Path) -> tuple[Path, Path, str]:
    """A hardened secret with the strongest link this host can aim at it.

    The target is itself valid and owner-restricted, so a reader that followed
    the link would return a usable secret rather than failing for some
    incidental reason - which is the only version of this test worth running.
    """
    target = tmp_path / "attacker_target"
    target.write_text(_SECRET, encoding="utf-8")
    harden_credential_path(target)
    link = tmp_path / "service.token"
    return link, target, plant_link_to_file(link, target)


def test_a_legitimate_secret_is_admitted(tmp_path: Path) -> None:
    """The admitted case. Without it every refusal below could be vacuous.

    A confirmation that answered ``False`` unconditionally would satisfy every
    other test in this module and would also break both readers outright.
    """
    path = tmp_path / "service.token"
    path.write_text(_SECRET, encoding="utf-8")
    harden_credential_path(path)

    named = path.lstat()
    descriptor = os.open(path, unfollowed_read_flags())
    try:
        assert confirm_opened_secret(descriptor, named=named, path=path)
        assert os.read(descriptor, 64).decode("utf-8") == _SECRET
    finally:
        os.close(descriptor)


def test_a_descriptor_opened_through_a_planted_link_is_refused(
    planted: tuple[Path, Path, str],
) -> None:
    """The whole choreography, against a real reparse point at the secret's name."""
    link, _target, kind = planted

    named = link.lstat()
    try:
        descriptor = os.open(link, unfollowed_read_flags())
    except OSError:
        pytest.skip(f"this host refused to open the planted {kind} at all")
    try:
        assert not confirm_opened_secret(descriptor, named=named, path=link), (
            f"the confirmation accepted a descriptor opened through a {kind}"
        )
    finally:
        os.close(descriptor)


def test_the_open_flags_alone_refuse_nothing_on_this_host(
    planted: tuple[Path, Path, str],
) -> None:
    """Both explicit steps blinded at once - and the secret comes through.

    This is the assertion that gives the two tests below their meaning. With the
    stat-by-name and the identity comparison both removed, all that remains is
    the open flag, and on a host without ``O_NOFOLLOW`` the read reaches the
    target's real bytes. The refusal disappears entirely, so neither explicit
    step is decorative.

    On a host that does have the flag the open itself refuses, which is the
    other half of the same claim and is asserted as such rather than skipped.
    """
    link, _target, kind = planted
    if kind != "symlink":
        pytest.skip("a junction has no file bytes behind it to leak")

    try:
        descriptor = os.open(link, unfollowed_read_flags())
    except OSError:
        assert hasattr(os, "O_NOFOLLOW"), (
            "the open refused a link on a host that has no O_NOFOLLOW to refuse with"
        )
        return
    try:
        leaked = os.read(descriptor, 64).decode("utf-8")
    finally:
        os.close(descriptor)

    assert not hasattr(os, "O_NOFOLLOW")
    assert leaked == _SECRET, (
        "the flag-only open neither refused the link nor reached the target"
    )


def test_the_stat_by_name_step_refuses_on_its_own(
    planted: tuple[Path, Path, str],
) -> None:
    """Blind the identity comparison; the regular-file test alone still refuses.

    A link's own ``lstat`` reports a reparse point rather than a regular file, so
    this step refuses before the descriptor is ever compared.
    """
    link, _target, kind = planted

    named = link.lstat()
    if not hasattr(os, "O_NOFOLLOW"):
        assert not stat.S_ISREG(named.st_mode), (
            f"the planted {kind} reported itself as a regular file"
        )


def test_the_identity_comparison_refuses_on_its_own(
    planted: tuple[Path, Path, str],
) -> None:
    """Blind the regular-file test; the device and inode comparison still refuses.

    The two steps are independently sufficient here, which is worth pinning: a
    future edit that drops one because "the other covers it" would leave a
    guarantee resting on a single check with no test saying so.
    """
    link, _target, kind = planted
    if kind != "symlink":
        pytest.skip("a junction is not opened as a file on this host")

    named = link.lstat()
    try:
        descriptor = os.open(link, unfollowed_read_flags())
    except OSError:
        pytest.skip(f"this host refused to open the planted {kind} at all")
    try:
        opened = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    assert (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino), (
        f"the descriptor behind a {kind} reported the link's own identity"
    )


def test_a_swapped_file_at_the_same_name_is_refused(tmp_path: Path) -> None:
    """The window the comparison exists for, without any link involved.

    A name inspected and then replaced by a different regular file before the
    open is the plain form of the attack: every by-name property still holds,
    and only the descriptor's identity reveals the substitution.
    """
    path = tmp_path / "service.token"
    path.write_text(_SECRET, encoding="utf-8")
    harden_credential_path(path)
    named = path.lstat()

    path.unlink()
    path.write_text("f" * 32, encoding="utf-8")
    harden_credential_path(path)

    descriptor = os.open(path, unfollowed_read_flags())
    try:
        assert not confirm_opened_secret(descriptor, named=named, path=path)
    finally:
        os.close(descriptor)
