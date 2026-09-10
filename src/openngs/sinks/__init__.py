"""Outbound sinks for the event stream.

The set is deliberately small. A broker sink (Kafka, NATS) is the obvious next one and is
tracked separately; the `Sink` protocol is the whole of what it would have to satisfy.
"""

from __future__ import annotations

from openngs.sinks.base import DeliveryError, Sink, to_cloudevent
from openngs.sinks.file import FileSink
from openngs.sinks.webhook import WebhookSink

__all__ = ["DeliveryError", "FileSink", "Sink", "WebhookSink", "to_cloudevent"]
