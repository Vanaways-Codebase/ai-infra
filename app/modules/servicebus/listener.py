"""Background listener for Azure Service Bus queues."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Optional

from app.modules.servicebus.models import ServiceBusEnvelope

logger = logging.getLogger(__name__)

MessageHandler = Callable[[ServiceBusEnvelope], Awaitable[None]]


class ServiceBusQueueListener:
    """Consumes messages from a Service Bus queue and invokes an async handler."""

    def __init__(
        self,
        *,
        connection_string: str,
        queue_name: str,
        handler: MessageHandler,
        max_message_count: int = 5,
        max_wait_time: float = 5.0,
        reconnect_backoff: float = 5.0,
        backoff_max: float = 60.0,
    ) -> None:
        if not connection_string:
            raise ValueError("Service Bus connection string is required")
        if not queue_name:
            raise ValueError("Service Bus queue name is required")
        self._connection_string = connection_string
        self._queue_name = queue_name
        self._handler = handler
        self._max_message_count = max(1, max_message_count)
        self._max_wait_time = max_wait_time
        self._initial_backoff = max(1.0, reconnect_backoff)
        self._backoff_max = max(self._initial_backoff, backoff_max)
        self._shutdown_event = asyncio.Event()
        self._task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("ServiceBusQueueListener already started")
        self._ensure_sdk()
        self._shutdown_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="servicebus-listener")

    async def stop(self) -> None:
        self._shutdown_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        backoff = self._initial_backoff
        while not self._shutdown_event.is_set():
            try:
                await self._receive_once()
                backoff = self._initial_backoff
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - network error path
                logger.exception("Service Bus listener encountered an error: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._backoff_max)

    def _ensure_sdk(self) -> None:
        try:
            from azure.servicebus.aio import ServiceBusClient  # noqa: F401
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "azure-servicebus package is required to use the Azure Service Bus listener."
                " Install it with 'pip install azure-servicebus'."
            ) from exc

    async def _receive_once(self) -> None:
        from azure.servicebus.aio import ServiceBusClient

        client = ServiceBusClient.from_connection_string(conn_str=self._connection_string)
        async with client:
            receiver = client.get_queue_receiver(queue_name=self._queue_name, max_wait_time=self._max_wait_time)
            async with receiver:
                while not self._shutdown_event.is_set():
                    messages = await receiver.receive_messages(
                        max_message_count=self._max_message_count,
                        max_wait_time=self._max_wait_time,
                    )
                    if not messages:
                        continue
                    for message in messages:
                        envelope = self._build_envelope(message)
                        try:
                            await self._handler(envelope)
                        except Exception as exc:  # pragma: no cover - handler error path
                            logger.exception(
                                "Service Bus handler failed for message %s: %s",
                                message.message_id,
                                exc,
                            )
                            await receiver.abandon_message(message)
                        else:
                            await receiver.complete_message(message)

    @staticmethod
    def _build_envelope(message: Any) -> ServiceBusEnvelope:
        body = ServiceBusQueueListener._decode_body(message)
        properties = None
        if getattr(message, "application_properties", None):
            # Convert to regular dict to detach from SDK object
            properties = dict(message.application_properties)
        return ServiceBusEnvelope(
            body=body,
            properties=properties,
            message_id=getattr(message, "message_id", None),
            correlation_id=getattr(message, "correlation_id", None),
            subject=getattr(message, "subject", None),
            content_type=getattr(message, "content_type", None),
            enqueued_time_utc=getattr(message, "enqueued_time_utc", None),
        )

    @staticmethod
    def _decode_body(message: Any) -> Optional[object]:
        try:
            sections = message.body
            if isinstance(sections, (bytes, bytearray)):
                body_bytes = bytes(sections)
            else:
                body_bytes = b"".join(
                    section if isinstance(section, (bytes, bytearray)) else bytes(section)
                    for section in sections
                )
        except TypeError:
            body_bytes = bytes(message)

        if not body_bytes:
            return None

        try:
            text = body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return body_bytes

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
