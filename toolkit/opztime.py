"""Watchdog: no toolkit run is allowed to hang for longer than two minutes.

Every tool that can loop over engine code calls `watch()` before doing work. The limit exists because
an emulated engine can sit in a loop the harness has not modelled yet, and a silent 20-minute hang
tells you nothing. Hitting the limit raises TimeoutError with the phase name, so the failure names
what was running: `engine sweep: exceeded 120 s`.

Override with OPZ_TIME_LIMIT=<seconds> (0 disables) when a run legitimately needs longer, e.g. a full
render of every factory engine to disk.
"""

import os
import signal

DEFAULT = 120.0


def _raise(signum, frame):
    raise TimeoutError(f"{_raise.phase}: exceeded {_raise.limit:.0f} s")


_raise.limit = DEFAULT
_raise.phase = "run"


def watch(phase="run", limit=None):
    """Start (or restart) the watchdog. Returns the limit actually installed."""
    limit = float(os.environ.get("OPZ_TIME_LIMIT", DEFAULT if limit is None else limit))
    _raise.phase, _raise.limit = phase, limit
    if limit <= 0:
        return 0.0
    signal.signal(signal.SIGALRM, _raise)
    signal.alarm(int(limit) or 1)
    return limit


def stop():
    signal.alarm(0)


def phase(name):
    """Rename the current phase so a timeout says which part was running."""
    _raise.phase = name
