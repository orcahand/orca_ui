"""Terminal output hygiene.

orca_core prints hardware diagnostics with plain ``print()`` — informative
once, but the connect ladder constructs several hand instances per attempt
and retries on a timer, so identical lines repeat dozens of times.
:func:`install_stdout_dedupe` wraps ``sys.stdout`` with a line filter that
lets the first occurrence through and drops exact repeats within a time
window. New information always prints; only repetition is suppressed.
"""

from __future__ import annotations

import io
import sys
import threading
import time

DEFAULT_WINDOW_S = 60.0
_SEEN_CAP = 2000


class _DedupingStdout(io.TextIOBase):
    def __init__(self, wrapped, window_s: float = DEFAULT_WINDOW_S):
        self._wrapped = wrapped
        self._window = window_s
        self._seen: dict[str, float] = {}
        self._partial = ""
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        with self._lock:
            self._partial += s
            while "\n" in self._partial:
                line, self._partial = self._partial.split("\n", 1)
                self._emit(line)
        return len(s)

    def _emit(self, line: str) -> None:
        key = line.strip()
        if key:
            now = time.monotonic()
            last = self._seen.get(key)
            self._seen[key] = now
            if last is not None and now - last < self._window:
                return
            if len(self._seen) > _SEEN_CAP:
                cutoff = now - self._window
                self._seen = {k: t for k, t in self._seen.items() if t > cutoff}
        self._wrapped.write(line + "\n")
        self._wrapped.flush()

    def flush(self) -> None:
        self._wrapped.flush()

    def isatty(self) -> bool:
        try:
            return self._wrapped.isatty()
        except Exception:
            return False


def install_stdout_dedupe(window_s: float = DEFAULT_WINDOW_S) -> None:
    if not isinstance(sys.stdout, _DedupingStdout):
        sys.stdout = _DedupingStdout(sys.stdout, window_s=window_s)
