"""What every outbound sink has to provide, and the wire shape they all send.

A sink publishes events outward. It never reads the graph, never writes to the log, and
sees exactly what `GET /events` returns and no more - a sink is an ordinary consumer that
happens to run in-process.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class DeliveryError(Exception):
    """A sink could not deliver an event.

    `retryable` is the sink's judgement about whether the same event sent again could
    succeed. A refused connection or a 503 is retryable; a 400 saying the body is
    malformed will say the same thing every time, and retrying it only delays every
    event behind it.
    """

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@runtime_checkable
class Sink(Protocol):
    """One outbound destination.

    `publish` either returns, meaning the event is delivered as far as this sink can tell,
    or raises `DeliveryError`. It must not swallow failures: the relay's cursor advances on
    a clean return, so a sink that hides an error silently drops the event.
    """

    name: str

    def publish(self, event: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


def to_cloudevent(event: dict[str, Any]) -> dict[str, Any]:
    """The stored row as a CloudEvents 1.0 structured-mode envelope.

    The log keeps OpenNGS's own bitemporal fields in their own columns, which is what makes
    them queryable, but on the wire they belong in `data`: CloudEvents reserves
    the top level for its own attributes, and an extension attribute may only be lowercase
    alphanumeric, which `valid_time` and the rest are not. So the envelope carries the spec
    attributes and nothing else, and every OpenNGS concept travels inside `data`.

    `id` is the event_id, which is what a consumer deduplicates on: delivery is
    at-least-once, so the same event can arrive twice and the id is how a consumer tells
    that from two genuine events.
    """
    data = dict(event["payload"])
    data["valid_time"] = event["valid_time"]
    data["transaction_time"] = event["transaction_time"]
    for field in ("recorded_by", "supersedes", "supersede_reason"):
        if event.get(field) is not None:
            data[field] = event[field]

    envelope: dict[str, Any] = {
        "specversion": event["specversion"],
        "id": event["event_id"],
        "source": event["source"],
        "type": event["type"],
        "time": event["time"],
        "datacontenttype": event["datacontenttype"],
        "data": data,
    }
    # `subject` is optional in CloudEvents and absent on the few events that describe no
    # single record, so it is omitted rather than sent as null.
    if event.get("subject") is not None:
        envelope["subject"] = event["subject"]
    return envelope
