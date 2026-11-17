"""App sessions: programs the console starts (orca_teleop, orca_rl) that send
joint targets over the app link while the console keeps the hand and its
safety. See ``docs/app-contract.md``."""

from orca_ui.hand.app.session import APPS, AppSessions

__all__ = ["APPS", "AppSessions"]
