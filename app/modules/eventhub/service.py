"""Lightweight Azure Event Hubs helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from azure.eventhub import EventData, EventHubConsumerClient, EventHubProducerClient

from app.core.config import settings


@dataclass(frozen=True)
class EventHubMessage:
    """Represents a single Event Hubs payload with optional metadata."""

    body: Any
    properties: Optional[Dict[str, Any]] = None


class EventHubClient:
    """Convenience wrapper that hides SDK wiring for common producer/consumer flows."""

    def __init__(
        self,
        *,
        connection_string: Optional[str] = None,
        eventhub_name: Optional[str] = None,
        consumer_group: Optional[str] = None,
        prefetch: Optional[int] = None,
    ) -> None:
        self._connection_string = (connection_string or settings.AZURE_EVENTHUB_CONNECTION_STRING).strip()
        self._eventhub_name = (eventhub_name or settings.AZURE_EVENTHUB_NAME).strip()
        self._consumer_group = consumer_group or settings.AZURE_EVENTHUB_CONSUMER_GROUP
        self._prefetch = prefetch if prefetch is not None else settings.AZURE_EVENTHUB_PREFETCH

        if not self._connection_string:
            raise RuntimeError("AZURE_EVENTHUB_CONNECTION_STRING is not configured")
        if not self._eventhub_name:
            raise RuntimeError("AZURE_EVENTHUB_NAME is not configured")

        self._producer: Optional[EventHubProducerClient] = None
        self._consumer: Optional[EventHubConsumerClient] = None

    def send(self, message: EventHubMessage) -> None:
        """Send a single event."""
        self.send_batch([message])

    def send_batch(self, messages: Iterable[EventHubMessage]) -> None:
        client = self._ensure_producer()
        event_data_batch = client.create_batch()
        for message in messages:
            event = self._to_event_data(message)
            try:
                event_data_batch.add(event)
            except ValueError:
                client.send_batch(event_data_batch)
                event_data_batch = client.create_batch()
                event_data_batch.add(event)
        if len(event_data_batch) > 0:
            client.send_batch(event_data_batch)

    def list_partitions(self) -> List[str]:
        """Return partition identifiers for the configured hub."""
        client = self._ensure_consumer()
        return client.get_partition_ids()

    def receive_batch(
        self,
        *,
        partition_id: str,
        max_events: int = 50,
        wait_time: float = 5.0,
    ) -> List[EventHubMessage]:
        """Pull a batch of events from a specific partition."""
        if max_events <= 0:
            return []
        client = self._ensure_consumer()
        events = client.receive_batch(
            partition_id=partition_id,
            max_batch_size=max_events,
            max_wait_time=wait_time,
        )
        return [self._from_event_data(event) for event in events]

    def close(self) -> None:
        if self._producer is not None:
            self._producer.close()
            self._producer = None
        if self._consumer is not None:
            self._consumer.close()
            self._consumer = None

    def __enter__(self) -> "EventHubClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _ensure_producer(self) -> EventHubProducerClient:
        if self._producer is None:
            self._producer = EventHubProducerClient.from_connection_string(
                conn_str=self._connection_string,
                eventhub_name=self._eventhub_name,
            )
        return self._producer

    def _ensure_consumer(self) -> EventHubConsumerClient:
        if self._consumer is None:
            self._consumer = EventHubConsumerClient.from_connection_string(
                conn_str=self._connection_string,
                consumer_group=self._consumer_group,
                eventhub_name=self._eventhub_name,
                prefetch=self._prefetch,
            )
        return self._consumer

    def _to_event_data(self, message: EventHubMessage) -> EventData:
        body_bytes = self._encode_body(message.body)
        event = EventData(body_bytes)
        if message.properties:
            for key, value in message.properties.items():
                event.properties[key] = value
        return event

    def _from_event_data(self, event: EventData) -> EventHubMessage:
        body = self._decode_body(event.body_as_str(encoding="utf-8"))
        props = dict(getattr(event, "properties", {}) or {})
        return EventHubMessage(body=body, properties=props or None)

    @staticmethod
    def _encode_body(body: Any) -> bytes:
        if body is None:
            return b""
        if isinstance(body, bytes):
            return body
        if isinstance(body, str):
            return body.encode("utf-8")
        return json.dumps(body).encode("utf-8")

    @staticmethod
    def _decode_body(body: str) -> Any:
        try:
            return json.loads(body)
        except (TypeError, json.JSONDecodeError):
            return body
