"""Handlers that respond to Service Bus messages."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict

from app.modules.servicebus.models import AudioProcessingMessage, ServiceBusEnvelope
from app.modules.transcription.job_processor import (
    TranscriptionJobError,
    dump_processed_transcription,
    process_transcription_job,
)

logger = logging.getLogger(__name__)


async def handle_audio_processing_message(envelope: ServiceBusEnvelope) -> None:
    """Entry point executed for each audio processing Service Bus message."""
    payload = envelope.body
    if not isinstance(payload, Dict):
        logger.warning(
            "Skipping Service Bus message %s with non-dict payload: %r",
            envelope.message_id,
            type(payload),
        )
        return

    try:
        message = AudioProcessingMessage.from_payload(payload)
    except ValueError as exc:
        logger.warning("Dropping malformed audio message %s: %s", envelope.message_id, exc)
        return

    logger.info(
        "Handling audio processing message callId=%s, message_id=%s",
        message.call_id,
        envelope.message_id,
    )

    def _process() -> None:
        processed = process_transcription_job(message.to_payload())
        logger.debug(
            "Processed transcription payload for callId=%s\n%s",
            message.call_id,
            dump_processed_transcription(processed),
        )

    try:
        await asyncio.to_thread(_process)
    except TranscriptionJobError as exc:
        logger.error(
            "Business validation failed for callId=%s: %s",
            message.call_id,
            exc,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception(
            "Unexpected failure processing callId=%s: %s",
            message.call_id,
            exc,
        )
