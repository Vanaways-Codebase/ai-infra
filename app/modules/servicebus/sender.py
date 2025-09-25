"""Lightweight helper for publishing messages to Azure Service Bus."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


class ServiceBusQueueSender:
    """Convenience wrapper to send JSON-friendly messages to a Service Bus queue."""

    def __init__(self, *, connection_string: str, queue_name: str) -> None:
        if not connection_string:
            raise ValueError("Service Bus connection string is required")
        if not queue_name:
            raise ValueError("Service Bus queue name is required")
        self._connection_string = connection_string
        self._queue_name = queue_name

    async def send(
        self,
        body: Any,
        *,
        application_properties: Optional[Dict[str, Any]] = None,
        message_id: Optional[str] = None,
        content_type: str = "application/json",
    ) -> None:
        try:
            from azure.servicebus import ServiceBusMessage
            from azure.servicebus.aio import ServiceBusClient
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "azure-servicebus package is required to send messages to Azure Service Bus."
                " Install it with 'pip install azure-servicebus'."
            ) from exc

        payload = self._serialize_body(body)
        message = ServiceBusMessage(
            body=payload,
            application_properties=application_properties,
            message_id=message_id,
            content_type=content_type,
        )
        client = ServiceBusClient.from_connection_string(conn_str=self._connection_string)
        async with client:
            sender = client.get_queue_sender(queue_name=self._queue_name)
            async with sender:
                await sender.send_messages(message)

    @staticmethod
    def _serialize_body(body: Any) -> bytes:
        if body is None:
            return b""
        if isinstance(body, (bytes, bytearray)):
            return bytes(body)
        if isinstance(body, str):
            return body.encode("utf-8")
        return json.dumps(body).encode("utf-8")
