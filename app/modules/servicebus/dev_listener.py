"""Standalone Service Bus listener for local testing."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Optional

from app.core.config import settings
from app.modules.servicebus.listener import ServiceBusQueueListener
from app.modules.servicebus.worker import handle_audio_processing_message

logger = logging.getLogger(__name__)


async def _wait_forever() -> None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows fallback
            pass

    await stop_event.wait()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

    connection = (settings.AZURE_SERVICEBUS_CONNECTION_STRING or "").strip()
    queue_name = (settings.AZURE_SERVICEBUS_QUEUE_NAME or "").strip()

    if not connection or not queue_name:
        raise RuntimeError(
            "AZURE_SERVICEBUS_CONNECTION_STRING and AZURE_SERVICEBUS_QUEUE_NAME must be set to run the listener"
        )

    listener = ServiceBusQueueListener(
        connection_string=connection,
        queue_name=queue_name,
        handler=handle_audio_processing_message,
        max_message_count=settings.AZURE_SERVICEBUS_MAX_MESSAGE_COUNT,
        max_wait_time=settings.AZURE_SERVICEBUS_MAX_WAIT_SECONDS,
    )

    await listener.start()
    logger.info("Service Bus listener running. Press Ctrl+C to stop.")

    try:
        await _wait_forever()
    finally:
        await listener.stop()
        logger.info("Service Bus listener stopped.")


if __name__ == "__main__":  # pragma: no cover - manual execution
    asyncio.run(main())
