"""POST each event to an HTTP endpoint, one request per event."""

from __future__ import annotations

import json
from typing import Any

import httpx

from openngs.sinks.base import DeliveryError, to_cloudevent

#: Sent as a 4xx but worth retrying anyway: the first is an explicit "try again", the
#: second is rate limiting, and neither says the event itself is wrong.
_RETRYABLE_CLIENT_ERRORS = frozenset({408, 429})


class WebhookSink:
    """CloudEvents structured mode: the whole envelope as the JSON body, under
    `application/cloudevents+json`. Structured rather than binary because it survives
    proxies, queues and log tooling that would drop the `ce-*` headers binary mode relies
    on, and because a consumer can persist the body verbatim.
    """

    def __init__(
        self,
        url: str,
        timeout: float = 10.0,
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = f"webhook({url})"
        self._url = url
        # `transport` exists so tests can drive the status codes this sink has to classify
        # without standing up a server; nothing in production passes it.
        self._client = httpx.Client(
            timeout=timeout,
            headers={"content-type": "application/cloudevents+json", **(headers or {})},
            transport=transport,
        )

    def publish(self, event: dict[str, Any]) -> None:
        body = json.dumps(to_cloudevent(event))
        try:
            response = self._client.post(self._url, content=body)
        except httpx.RequestError as exc:
            # Never reached the server, or the reply never came back: always worth another
            # attempt, and the event may well have been processed already - which is why
            # consumers deduplicate on the event id.
            raise DeliveryError(f"{type(exc).__name__}: {exc}", retryable=True) from exc

        if response.is_success:
            return
        retryable = response.status_code >= 500 or response.status_code in _RETRYABLE_CLIENT_ERRORS
        raise DeliveryError(
            f"HTTP {response.status_code}: {response.text[:200]}", retryable=retryable
        )

    def close(self) -> None:
        self._client.close()
