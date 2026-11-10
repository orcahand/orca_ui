"""Auto-open the UI in a browser app window and close it again on exit.

Moved from the original ``app.py``. If a Chromium-based browser is found, it
is launched as a subprocess in ``--app`` mode with its own profile so the
window can be deterministically closed when the server stops. Otherwise the
default browser opens the URL (and stays open).

The profile is kept between runs, one per port, in ``~/.orca_ui/browser/``, so
the guide's cached media and any sign-in survive a restart. A browser can hold
a profile open only once, hence one per port.
"""

from __future__ import annotations

import atexit
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit
import webbrowser

_browser_proc = None


def _find_chromium():
    """Return a path to a Chromium-based browser, or None."""
    mac_apps = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for path in mac_apps:
        if os.path.exists(path):
            return path
    for name in ("google-chrome", "chromium", "chromium-browser",
                 "brave-browser", "microsoft-edge"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _profile_dir(url) -> Path:
    """The kept browser profile for the console served at ``url``."""
    folder = Path.home() / ".orca_ui" / "browser" / f"port-{urlsplit(url).port}"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder


def open_browser(url):
    """Open the UI in a browser.

    If a Chromium-based browser is found, launch a dedicated app window as a
    subprocess we can close when the program exits. Otherwise fall back to the
    default browser (which opens but cannot be closed automatically).
    """
    global _browser_proc
    chromium = _find_chromium()
    if chromium:
        try:
            # start_new_session: put Chrome (and its helper processes) in their
            # own process group so we can signal the whole group on exit.
            # DEVNULL: Chrome inherits the terminal otherwise and floods it
            # with updater/GCM/crashpad logs.
            _browser_proc = subprocess.Popen([
                chromium, f"--app={url}",
                f"--user-data-dir={_profile_dir(url)}",
                "--no-first-run", "--no-default-browser-check",
                # The console closes the window with a signal; don't offer to restore it next time.
                "--hide-crash-restore-bubble",
            ], start_new_session=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            atexit.register(close_browser)
            return
        except Exception:
            _browser_proc = None
    webbrowser.open(url)


def close_browser():
    """Close the app-window browser (and its helper processes) on exit."""
    global _browser_proc
    proc, _browser_proc = _browser_proc, None
    if proc and proc.poll() is None:
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)  # graceful: whole Chrome process group
            try:
                proc.wait(timeout=3)
            except Exception:
                os.killpg(pgid, signal.SIGKILL)  # force if it ignores SIGTERM
        except ProcessLookupError:
            pass


def launch_after_startup(url, delay_s: float = 1.5):
    """Open the browser once the server is (very likely) listening, and make
    SIGINT/SIGTERM close the app window before exiting.

    Handling the signals ourselves (rather than relying on
    KeyboardInterrupt -> atexit) keeps the window teardown deterministic no
    matter how the serving loop swallows interrupts.
    """
    def _on_stop(signum, frame):
        close_browser()
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_stop)
    signal.signal(signal.SIGTERM, _on_stop)
    threading.Timer(delay_s, open_browser, args=(url,)).start()
