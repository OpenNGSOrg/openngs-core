"""Following the event log and publishing outward.

The relay is an ordinary consumer of `GET /events`, run as a process: it reads forward from
a cursor, hands each event to a sink, and advances the cursor only once the sink says the
event is delivered. That single ordering rule is what makes delivery at-least-once - a
crash, a kill, or a failed send leaves the cursor pointing at the last *delivered* event,
so everything after it is sent again.

Nothing here writes to the `Event` table. The cursor lives in its own file, because
delivery is a property of one subscriber and not of the log (invariant 1).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openngs.sinks import DeliveryError, Sink, to_cloudevent
from openngs.store import Database, list_events, log_tip


@dataclass
class RelayState:
    """One subscriber's position in the log, persisted beside it."""

    path: Path
    cursor: str | None = None
    delivered: int = 0

    @classmethod
    def load(cls, path: Path) -> RelayState:
        if not path.exists():
            return cls(path=path)
        raw = json.loads(path.read_text())
        return cls(path=path, cursor=raw.get("cursor"), delivered=int(raw.get("delivered", 0)))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Written whole and renamed over the old file, so a crash mid-write cannot leave a
        # truncated cursor - which would silently re-deliver from the beginning of the log.
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"cursor": self.cursor, "delivered": self.delivered}, indent=2) + "\n"
        )
        temporary.replace(self.path)


def _write_dead_letter(path: Path, event: dict[str, Any], reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"reason": reason, "event": to_cloudevent(event)}, separators=(",", ":"))
            + "\n"
        )


def deliver(
    sink: Sink,
    event: dict[str, Any],
    max_retries: int,
    backoff: float,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Publish one event, retrying a retryable failure with exponential backoff.

    Raises the last `DeliveryError` when the attempts run out, or immediately when the sink
    calls the failure permanent - a 400 will still be a 400 in eight seconds, and retrying
    it only delays every event queued behind it.
    """
    attempt = 0
    while True:
        try:
            sink.publish(event)
            return
        except DeliveryError as exc:
            if not exc.retryable or attempt >= max_retries:
                raise
            sleep(backoff * (2**attempt))
            attempt += 1


def run_relay(
    db_url: str,
    sink: Sink,
    state: RelayState,
    poll_interval: float = 5.0,
    batch_size: int = 100,
    max_retries: int = 5,
    backoff: float = 1.0,
    dead_letter: Path | None = None,
    types: Sequence[str] | None = None,
    source: str | None = None,
    once: bool = False,
    should_stop: Callable[[], bool] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Read forward from the cursor and publish, until drained (`once`) or stopped.

    A batch is read with a fresh connection each pass rather than holding one open: the
    relay spends most of its life idle, and a connection left open across a long quiet
    period is the one that turns out to be dead when something finally happens.

    When `dead_letter` is set, an event that exhausts its retries is written there and the
    cursor moves past it, so one poisonous event cannot wedge the whole stream. Without it
    the relay stops instead, because skipping an event with nowhere to record that it was
    skipped would lose it silently.
    """
    total = 0
    while True:
        with Database.connect(db_url) as db:
            events = list_events(
                db, limit=batch_size, after=state.cursor, types=types, source=source
            )

        for event in events:
            try:
                deliver(sink, event, max_retries, backoff, sleep)
            except DeliveryError as exc:
                if dead_letter is None:
                    raise
                _write_dead_letter(dead_letter, event, str(exc))
            # Only now: everything up to and including this event is delivered, or recorded
            # as undeliverable. A cursor advanced any earlier would drop events on a crash.
            state.cursor = event["event_id"]
            state.delivered += 1
            state.save()
            total += 1
            if on_event is not None:
                on_event(event)

        if should_stop is not None and should_stop():
            return total
        if once and not events:
            return total
        if not events:
            sleep(poll_interval)


def initial_cursor(db_url: str, start: str) -> str | None:
    """Where a subscriber with no state file begins.

    `now` is the default because pointing a fresh relay at an established database would
    otherwise replay its entire history at whatever is on the other end. `beginning` is
    the explicit way to ask for that backfill.
    """
    if start == "beginning":
        return None
    if start == "now":
        with Database.connect(db_url) as db:
            return log_tip(db)
    return start  # an explicit event_id to resume after
