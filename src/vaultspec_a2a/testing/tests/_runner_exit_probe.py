"""Subprocess-only probe that intentionally blocks interpreter shutdown."""

import threading


def test_result_precedes_process_exit() -> None:
    blocker = threading.Event()
    threading.Thread(target=blocker.wait, name="intentional-exit-blocker").start()
