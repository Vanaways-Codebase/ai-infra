"""Shared transcription job processing logic for HTTP and background consumers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import groq

from app.core.config import settings
from app.modules.asr.service import TranscriptionResult, transcribe_from_url
from app.modules.transcription import service as transcription_service

logger = logging.getLogger(__name__)


class TranscriptionJobError(Exception):
    """Domain-specific error raised when transcription job payloads are invalid."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class ProcessedTranscription:
    """Final payload returned to API clients and queue consumers."""

    data: Dict[str, Any]
    transcription: Optional[TranscriptionResult] = None


def _ensure_groq_client(provided: Optional[groq.Groq] = None) -> groq.Groq:
    if provided is not None:
        return provided
    api_key = (settings.GROQ_API_KEY or "").strip()
    if not api_key:
        raise TranscriptionJobError("GROQ_API_KEY is not configured", status_code=500)
    return groq.Groq(api_key=api_key)


def _extract_core_fields(payload: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str], Dict[str, Any]]:
    call_id = payload.get("callId") or payload.get("call_id")
    recording_url = payload.get("recordingUrl") or payload.get("recording_url")
    call_transcript = (
        payload.get("call_transcript")
        or payload.get("transcript")
        or payload.get("callTranscript")
    )
    meta = payload.get("meta") or {}

    if not call_id:
        raise TranscriptionJobError("callId is required", status_code=400)
    if not call_transcript and not recording_url:
        raise TranscriptionJobError(
            "Either 'call_transcript' or 'recordingUrl' must be provided",
            status_code=400,
        )

    return str(call_id), recording_url, call_transcript, meta


def _maybe_transcribe(recording_url: Optional[str]) -> Optional[TranscriptionResult]:
    if not recording_url:
        return None
    try:
        return transcribe_from_url(recording_url)
    except Exception as exc:  # pragma: no cover - propagates to caller with context
        logger.exception("Transcription failed for recording %s", recording_url)
        raise TranscriptionJobError(f"Transcription failed: {exc}", status_code=502) from exc


def _ensure_transcript_text(
    existing_text: Optional[str], transcription: Optional[TranscriptionResult]
) -> str:
    if existing_text and existing_text.strip():
        return existing_text
    if transcription and transcription.text:
        return transcription.text
    raise TranscriptionJobError("Transcription text is empty", status_code=502)


def process_transcription_job(
    payload: Dict[str, Any],
    *,
    groq_client: Optional[groq.Groq] = None,
    publish_to_kafka: bool = False,
) -> ProcessedTranscription:
    """Process a transcription payload.

    Args:
        payload: Incoming message body.
        groq_client: Optional Groq client instance.
        publish_to_kafka: Placeholder flag retained for compatibility.

    Returns:
        ProcessedTranscription containing the API-friendly payload and optional
        low-level transcription result details.
    """

    client = _ensure_groq_client(groq_client)
    call_id, recording_url, transcript_text, meta = _extract_core_fields(payload)
    transcription = _maybe_transcribe(recording_url)
    transcript_text = _ensure_transcript_text(transcript_text, transcription)

    sentiment, sentiment_score = transcription_service.analyze_sentiment(client, transcript_text)
    rating, rating_explanation = transcription_service.rate_call(client, transcript_text)
    keywords = transcription_service.extract_keywords(client, transcript_text)
    client_details = transcription_service.get_client_details(client, transcript_text)
    formatted_transcript = transcription_service.make_transcription_readable(client, transcript_text)

    response_payload: Dict[str, Any] = {
        "callId": call_id,
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "keywords": keywords,
        "call_rating": rating,
        "rating_explanation": rating_explanation,
        "buyer_intent": buyer_intent,
        "buyer_intent_score": transcription.buyer_intent_score if transcription else None,
        "client_email": client_details.get("email", ""),
        "client_name": client_details.get("name", ""),
        "call_transcript": transcript_text,
        "formatted_transcript": formatted_transcript,
        "meta": meta,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    if "timestamp" in payload:
        response_payload["timestamp"] = payload["timestamp"]

    if publish_to_kafka:
        logger.warning("Kafka publishing requested but not implemented; skipping emit.")

    if transcription:
        response_payload["transcription"] = {
            "status": transcription.status,
            "id": transcription.id,
            "call_summary": transcription.call_summary,
            "call_analysis": transcription.call_analysis,
            "buyer_intent": transcription.buyer_intent,
            "buyer_intent_score": transcription.buyer_intent_score,
            "agent_recommendation": transcription.agent_recommendation,
            "structured_transcript": transcription.structured_transcript,
            "keywords": transcription.keywords,
            "mql_assessment": transcription.mql_assessment,
            "sentiment_analysis": transcription.sentiment_analysis,
            "customer_rating": transcription.customer_rating,
            "call_type": transcription.call_type,
            "summary": transcription.summary,
            "vehicle_tags": transcription.vehicle_tags,
            "contact_extraction": transcription.contact_extraction,
        }

    logger.info("Processed transcription job for callId=%s", call_id)
    return ProcessedTranscription(data=response_payload, transcription=transcription)


def dump_processed_transcription(result: ProcessedTranscription) -> str:
    """Serialize processed transcription payload as JSON for auditing/logging."""
    return json.dumps(result.data, ensure_ascii=False, indent=2)
