"""What the console remembers per app, one JSON file each in ``<root>/<app>.json``:
the launch command, the last settings schema the app sent, and the values.

Kept in the backend rather than the browser, so the MCP server and every
browser see the same values, and the app gets them in ``hello_ok``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from orca_ui.hand.app.protocol import clean_values

logger = logging.getLogger(__name__)

FIELDS = ("command", "schema", "values")


class AppStore:
    def __init__(self, root: str | os.PathLike):
        self._root = Path(root)
        self._lock = threading.Lock()

    def load(self, app: str) -> dict:
        with self._lock:
            return self._read(app)

    def update(self, app: str, **fields) -> dict:
        """Merge ``fields`` (command, schema, values) into the app's record."""
        with self._lock:
            record = self._read(app)
            record.update({k: v for k, v in fields.items() if k in FIELDS})
            path = self._root / f"{app}.json"
            try:
                self._root.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(record, indent=2))
                os.replace(tmp, path)
            except OSError:
                logger.exception("could not save %s", path)
            return record

    def _read(self, app: str) -> dict:
        path = self._root / f"{app}.json"
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError):
            logger.warning("ignoring unreadable %s", path)
            data = {}
        schema, values = data.get("schema"), data.get("values")
        return {
            "command": str(data.get("command") or ""),
            "schema": schema if isinstance(schema, list) else [],
            "values": clean_values(values),  # a hand-edited NaN must not wedge a start
        }
