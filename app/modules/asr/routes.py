import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.modules.recording.service import RingCentralRateLimitActive
from pydantic import ValidationError

from .schemas import (
    AudioProcessingMessageRequest,
    ContactExtraction,
    TranscriptUtterance,
    TranscribeResponse,
    TranscribeUrlRequest,
    TranscribeIdRequest,
    VehicleTag,
)
from .service import transcribe, manual_transcribe

router = APIRouter()
logger = logging.getLogger(__name__)
# Configure logger for this module
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
logger.setLevel(logging.INFO)


@router.post("/transcribe/url", response_model=TranscribeResponse, summary="Transcribe audio from a URL")
async def transcribe_url(body: TranscribeUrlRequest) -> TranscribeResponse:
    """Transcribe audio from a URL"""
    try:
        transcription_result = await transcribe(url=str(body.audio_url))
        logger.info("Transcription successful for ID=%s ✅", body.ring_central_id)
        return _build_transcribe_response(transcription_result, ring_central_id=body.ring_central_id)
    except RingCentralRateLimitActive as rle:
        retry_after = max(1, int(getattr(rle, "retry_after", 30.0)))
        raise HTTPException(
            status_code=429, 
            detail="RingCentral rate limit active", 
            headers={"Retry-After": str(retry_after)}
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Transcription failed for url=%s: %s", body.audio_url, exc)
        raise HTTPException(status_code=500, detail=f"Failed to transcribe URL: {exc}") from exc

@router.post("/manual-process", summary="Manually transcribe recent calls")
async def manual_transcribe_endpoint(limit: int = 1) -> Dict[str, Any]:
    """Kick off manual transcription for the latest calls."""
    try:
        processed = await manual_transcribe(limit=limit)
        return {"processed": processed, "count": len(processed)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Manual transcription failed for limit=%s: %s", limit, exc)
        raise HTTPException(status_code=500, detail=f"Failed to manually transcribe: {exc}") from exc


@router.post("/transcribe/id", response_model=TranscribeResponse, summary="Transcribe audio from RingCentral recording ID")
async def transcribe_id(body: TranscribeIdRequest) -> TranscribeResponse:
    """Transcribe audio from a RingCentral recording ID."""
    try:
        transcription_result = await transcribe(recording_id=body.recording_id)
        logger.info("Transcription successful for recording_id=%s", body.recording_id)
        return _build_transcribe_response(transcription_result, ring_central_id=body.recording_id)
    except RingCentralRateLimitActive as rle:
        retry_after = max(1, int(getattr(rle, "retry_after", 30.0)))
        raise HTTPException(
            status_code=429, 
            detail="RingCentral rate limit active", 
            headers={"Retry-After": str(retry_after)}
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Transcription failed for recording_id=%s: %s", body.recording_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to transcribe recording: {exc}") from exc



@router.post("/transcribe/file", response_model=TranscribeResponse, summary="Transcribe uploaded audio file")
async def transcribe_file(
    file: UploadFile = File(...),
) -> TranscribeResponse:
    try:
        suffix = os.path.splitext(file.filename or "upload")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp.flush()
            tmp_path = tmp.name
            
        try:
            # Use our new async transcribe function directly with the file URL
            transcription_result = await transcribe(url=f"file://{tmp_path}")
            return _build_transcribe_response(transcription_result)
        finally:
            # Clean up the temporary file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to transcribe file: {exc}")


def _build_transcribe_response(result, *, ring_central_id: Optional[str] = None) -> TranscribeResponse:
    """Build the standardized API response from the transcription result."""
    # Handle error status
    if result.status.lower() in {"error", "failed"}:
        raise HTTPException(status_code=400, detail="Transcription failed")

    transcription_turns = _normalize_transcription(result.structured_transcript)
    keywords = _normalize_keywords(result.keywords)
    tags = _normalize_tags(result.vehicle_tags)
    contact_extraction = result.contact_extraction
    if contact_extraction is None:
        contact_extraction = ContactExtraction()

    return TranscribeResponse(
        ring_central_id=ring_central_id,
        rating=_safe_float(result.customer_rating),
        call_type=(result.call_type or "").strip(),
        mql_score=_safe_float(result.mql_assessment),
        sentiment_score=_safe_float(result.sentiment_analysis),
        keywords=keywords,
        transcription=transcription_turns,
        tags=tags,
        summary=(result.summary or result.call_summary or "").strip(),
        call_analysis=(result.call_analysis or "").strip() or None,
        buyer_intent=_safe_float(result.buyer_intent_score),
        buyer_intent_reason=(result.buyer_intent_reason or "").strip() or None,
        agent_recommendation=(result.agent_recommendation or "").strip() or None,
        contact_extraction=contact_extraction,
    )


def _normalize_transcription(data: Optional[List[Dict[str, Any]]]) -> List[TranscriptUtterance]:
    if not data:
        return []

    turns: List[TranscriptUtterance] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or item.get("text") or "").strip()
        if not message:
            continue
        speaker = str(item.get("speaker") or "").strip().lower()
        if speaker not in {"agent", "customer"}:
            speaker = "agent"
        timestamp = _normalize_timestamp(item.get("timestamp") or item.get("start"))
        turns.append(
            TranscriptUtterance(
                speaker=speaker,
                message=message,
                timestamp=timestamp,
            )
        )
    return turns


def _normalize_timestamp(raw: Any) -> Dict[str, str]:
    if isinstance(raw, dict):
        if "$date" in raw and isinstance(raw["$date"], str):
            return {"$date": raw["$date"]}
        if "iso" in raw and isinstance(raw["iso"], str):
            return {"$date": raw["iso"]}
        if "value" in raw and isinstance(raw["value"], str):
            return {"$date": raw["value"]}
    if isinstance(raw, str) and raw:
        return {"$date": raw}
    if isinstance(raw, (int, float)):
        base_time = datetime.now(timezone.utc)
        return {"$date": (base_time + timedelta(seconds=float(raw))).isoformat()}
    return {"$date": datetime.now(timezone.utc).isoformat()}


def _normalize_keywords(raw: Optional[List[Any]]) -> List[str]:
    if not raw:
        return []
    keywords: List[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item).strip()
        lowered = text.lower()
        if text and lowered not in seen:
            keywords.append(text)
            seen.add(lowered)
    return keywords


def _normalize_tags(raw: Optional[Sequence[Any]]) -> List[VehicleTag]:
    if not raw:
        return []
    tags: List[VehicleTag] = []
    for item in raw:
        if isinstance(item, VehicleTag):
            tags.append(item)
            continue
        if isinstance(item, dict):
            try:
                tags.append(VehicleTag.model_validate(item))
            except ValidationError:
                continue
    return tags


def _safe_float(value: Optional[Any], default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
