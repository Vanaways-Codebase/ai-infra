import logging
import mimetypes
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.modules.recording.service import fetch_recording_bytes

from .schemas import (
    AudioProcessingMessageRequest,
    TranscriptUtterance,
    TranscribeResponse,
    TranscribeUrlRequest,
)
from .service import _status_name, transcribe_from_file_path, transcribe_from_url

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/transcribe/url", response_model=TranscribeResponse, summary="Transcribe audio from a URL")
async def transcribe_url(body: TranscribeUrlRequest) -> TranscribeResponse:
    try:
        transcription_result = await _to_thread(_transcribe_ringcentral_content, str(body.audio_url))
        return _build_transcribe_response(transcription_result, ring_central_id=body.ring_central_id)
    except HTTPException:
        raise
    except Exception as primary_error:
        logger.warning(
            "RingCentral download failed for url=%s: %s",
            body.audio_url,
            primary_error,
        )
        try:
            transcription_result = await _to_thread(transcribe_from_url, str(body.audio_url))
            return _build_transcribe_response(transcription_result, ring_central_id=body.ring_central_id)
        except HTTPException:
            raise
        except Exception as fallback_error:
            logger.error(
                "Fallback transcription failed for url=%s: %s",
                body.audio_url,
                fallback_error,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to transcribe URL: {fallback_error or primary_error}",
            ) from fallback_error


@router.post(
    "/transcribe/message",
    response_model=TranscribeResponse,
    summary="Transcribe audio message payload (RingCentral queue format)",
)
async def transcribe_message(body: AudioProcessingMessageRequest) -> TranscribeResponse:
    request = TranscribeUrlRequest(audio_url=body.audio_url, ring_central_id=body.ring_central_id)
    return await transcribe_url(request)


@router.post("/transcribe/file", response_model=TranscribeResponse, summary="Transcribe uploaded audio file")
async def transcribe_file(
    file: UploadFile = File(...),
) -> TranscribeResponse:
    try:
        suffix = os.path.splitext(file.filename or "upload")[1]
        with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp.flush()
            transcription_result = await _to_thread(transcribe_from_file_path, tmp.name)
        return _build_transcribe_response(transcription_result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to transcribe file: {exc}")


async def _to_thread(func, *args, **kwargs):
    try:
        import anyio

        return await anyio.to_thread.run_sync(lambda: func(*args, **kwargs))
    except Exception:
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


def _transcribe_ringcentral_content(audio_url: str):
    try:
        data, content_type, filename = fetch_recording_bytes(audio_url, None)
    except Exception as exc:
        logger.error("RingCentral fetch failed for url=%s: %s", audio_url, exc)
        raise
    suffix = Path(filename).suffix
    if not suffix:
        suffix = mimetypes.guess_extension(content_type or "") or ".mp3"

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp.flush()
            tmp_path = tmp.name
        return transcribe_from_file_path(tmp_path)
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _build_transcribe_response(result, *, ring_central_id: Optional[str] = None) -> TranscribeResponse:
    status = _status_name(result.status)
    if status.lower() in {"error", "failed"}:
        raise HTTPException(status_code=400, detail="Transcription failed")

    transcription_turns = _normalize_transcription(result.structured_transcript)
    keywords = _normalize_keywords(result.keywords)
    tags = _normalize_tags(result.vehicle_tags)

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
        contact_extraction=result.contact_extraction or None,
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
        timestamp = _normalize_timestamp(item.get("timestamp"))
        turns.append(
            TranscriptUtterance(
                speaker=speaker,  # type: ignore[arg-type]
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


def _normalize_tags(raw: Optional[Dict[str, Any]]) -> List[str]:
    if not raw:
        return []
    tags: List[str] = []
    for key, value in raw.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        count = 1
        try:
            count_candidate = int(value)
            if count_candidate > 0:
                count = count_candidate
        except (TypeError, ValueError):
            count = 1
        tags.extend([key_text] * count)
    deduped: List[str] = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
    return deduped


def _safe_float(value: Optional[Any], default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
