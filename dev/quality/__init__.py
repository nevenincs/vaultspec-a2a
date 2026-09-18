"""Read-only instruments that measure the source tree's quality.

Each module here answers one question about the code and answers it the same
way every time it is asked: same finding set, same ordering, same exit code.
Two rules hold across all of them, and both exist because their absence was a
defect rather than a preference:

* A measurement that could not be taken is reported as unavailable, never as
  clean. "Reported nothing" is not "found nothing".
* Output is signal, not transcript. Green is silent; red is a bounded,
  grouped, deterministically ordered summary that names the full-detail
  command rather than pasting it.

See Also:
    :mod:`dev.audit`
        The advisory scanners, which yield leads rather than verdicts.
"""
