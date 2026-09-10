"""Append each event to a JSON Lines file.

Useful in three places: as the sink under test, as a way to see what a relay would send
before pointing it at anything real, and as an ordinary local subscriber - `tail -f` on
the file is a working event feed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openngs.sinks.base import DeliveryError, to_cloudevent


class FileSink:
    def __init__(self, path: Path) -> None:
        self.name = f"file({path})"
        self._path = path

    def publish(self, event: dict[str, Any]) -> None:
        line = json.dumps(to_cloudevent(event), separators=(",", ":"))
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Opened per event and closed again, so the line is on disk before the relay
            # advances its cursor. A buffered handle would let the cursor claim delivery
            # for lines still sitting in memory when the process dies.
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            # A full or unwritable disk is worth retrying: it is a property of the moment,
            # not of the event.
            raise DeliveryError(f"cannot write {self._path}: {exc}", retryable=True) from exc

    def close(self) -> None:
        return None
