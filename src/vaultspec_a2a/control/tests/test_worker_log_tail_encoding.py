"""Decoding of the worker stderr tail across a byte-offset seek.

The tail is taken by seeking a fixed number of bytes back from the end of the
log, so for any log carrying non-ASCII provider output the read routinely starts
inside a character rather than on a boundary. These tests use real multibyte
output because ASCII cannot land mid-character at all - the very reason a tail
reader can look correct for years and still open every localized diagnostic with
replacement characters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..worker_management import _read_log_tail

if TYPE_CHECKING:
    from pathlib import Path

# Provider CLIs emit prose, so their stderr carries whatever language the user
# runs in. Each sample below is chosen for its UTF-8 width - three bytes for CJK,
# four for an astral-plane emoji, two for a combining accent - and each ENDS on a
# multibyte character, so taking the last N bytes cuts inside one.
_SAMPLES = [
    pytest.param("認証に失敗しました: トークンが無効です。", id="cjk"),
    pytest.param("build failed, retrying \U0001f525\U0001f525", id="astral"),
    pytest.param("connexion refusée par le démon arrêté", id="combining"),
]

# Byte counts to keep from the end of the log. Walking a contiguous range steps
# the cut through every residue class of the 2-, 3-, and 4-byte characters above,
# so the mid-character case is exercised rather than hoped for.
_TAIL_WIDTHS = list(range(1, 14))


def _write_log(tmp_path: Path, name: str, text: str) -> Path:
    log = tmp_path / name
    log.write_bytes(text.encode("utf-8"))
    return log


def _longest_fitting_suffix(text: str, max_bytes: int) -> str:
    """The tail the caller is owed, derived from what a tail IS.

    Stated independently of the reader: keep as much of the end of *text* as
    ``max_bytes`` bytes of UTF-8 can hold, cut on a character boundary. Written
    as a search over suffixes rather than as a byte-offset-and-trim, so it shares
    no logic with the implementation it is used to check - a reader that trimmed
    the wrong number of bytes, or discarded more than it had to, disagrees here.
    """
    for start in range(len(text) + 1):
        if len(text[start:].encode("utf-8")) <= max_bytes:
            return text[start:].strip()
    return ""


@pytest.mark.parametrize("message", _SAMPLES)
def test_the_samples_really_do_cut_mid_character(message: str) -> None:
    """Guard the guard: prove these widths land inside characters.

    Without this, a sample whose cuts all happened to fall on boundaries would
    make every assertion below pass while testing nothing.
    """
    raw = message.encode("utf-8")
    # A UTF-8 continuation byte matches 0b10xxxxxx.
    mid = [width for width in _TAIL_WIDTHS if raw[-width] & 0xC0 == 0x80]
    assert mid, f"no width in {_TAIL_WIDTHS} cuts inside a character of {message!r}"


@pytest.mark.parametrize("message", _SAMPLES)
@pytest.mark.parametrize("width", _TAIL_WIDTHS)
def test_tail_never_opens_with_a_broken_character(
    tmp_path: Path, message: str, width: int
) -> None:
    """Every seek alignment must yield clean text, not a stranded fragment.

    The two properties below are necessary but not sufficient on their own: at
    the narrowest widths the correct tail is the EMPTY string, and an empty tail
    satisfies both trivially - it holds no replacement character and is a suffix
    of anything. A reader that discarded more than the stranded bytes, or
    everything, would pass. So the tail is also held against the independently
    derived expectation of how much it should have kept.
    """
    log = _write_log(tmp_path, "worker-autospawn-1.stderr.log", message)

    tail = _read_log_tail(log, max_bytes=width)

    assert "�" not in tail, (
        f"tail cut at {width} bytes opened with a replacement character: {tail!r}"
    )
    # Whatever survived the cut is a genuine suffix of the original text.
    assert message.endswith(tail)
    assert tail == _longest_fitting_suffix(message, width), (
        f"tail cut at {width} bytes kept {len(tail)} characters where the widest "
        f"boundary-aligned suffix that fits is "
        f"{len(_longest_fitting_suffix(message, width))}"
    )


@pytest.mark.parametrize("message", _SAMPLES)
def test_tail_reads_a_whole_short_log_verbatim(tmp_path: Path, message: str) -> None:
    """A log inside the cap is not truncated, so it round-trips exactly."""
    log = _write_log(tmp_path, "worker-autospawn-2.stderr.log", message)

    assert _read_log_tail(log, max_bytes=4096) == message


def test_tail_decodes_as_utf8_not_the_host_code_page(tmp_path: Path) -> None:
    """The log is UTF-8 because the worker writes UTF-8, whatever the host locale.

    Decoding with the ambient code page would return mojibake of a similar
    length, which no length assertion would catch.
    """
    log = _write_log(tmp_path, "worker-autospawn-3.stderr.log", "日本語")

    assert _read_log_tail(log, max_bytes=4096) == "日本語"


def test_undecodable_bytes_degrade_instead_of_raising(tmp_path: Path) -> None:
    """A truncated or corrupt log must still yield a diagnostic, never an error.

    This tail is read while reporting why a worker died; raising here would
    replace the real failure with an encoding traceback.
    """
    log = tmp_path / "worker-autospawn-4.stderr.log"
    log.write_bytes(b"start \xff\xfe not utf-8 end")

    tail = _read_log_tail(log, max_bytes=4096)

    assert tail.startswith("start")
    assert tail.endswith("end")
