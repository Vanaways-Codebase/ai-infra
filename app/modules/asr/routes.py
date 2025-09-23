import os
import tempfile

from fastapi import APIRouter, UploadFile, File, HTTPException

from .schemas import TranscribeUrlRequest, TranscribeResponse
from .service import transcribe_from_url, transcribe_from_file_path, _status_name


router = APIRouter()


@router.post("/transcribe/url", response_model=TranscribeResponse, summary="Transcribe audio from a URL")
async def transcribe_url(body: TranscribeUrlRequest) -> TranscribeResponse:
    try:
        t = await _to_thread(transcribe_from_url, str(body.audio_url))
        status = _status_name(t.status)
        if status.lower() in {"error", "failed"}:
            raise HTTPException(status_code=400, detail="Transcription failed")
        return TranscribeResponse(
            status=status,
            text=t.text or "",
            confidence=t.confidence,
            id=t.id,
            call_summary=t.call_summary,
            call_analysis=t.call_analysis,
            buyer_intent=t.buyer_intent,
            agent_recommendation=t.agent_recommendation,
            structured_transcript=t.structured_transcript,
            keywords=t.keywords,
            mql_assessment=t.mql_assessment,
            sentiment_analysis=t.sentiment_analysis,
            customer_rating=t.customer_rating,
            call_type=t.call_type,
            summary=t.summary,
            vehicle_tags=t.vehicle_tags,
            contact_extraction=t.contact_extraction,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to transcribe URL: {e}")


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
            t = await _to_thread(transcribe_from_file_path, tmp.name)
        status = _status_name(t.status)
        if status.lower() in {"error", "failed"}:
            raise HTTPException(status_code=400, detail="Transcription failed")
        return TranscribeResponse(
            status=status,
            text=t.text or "",
            confidence=t.confidence,
            id=t.id,
            call_summary=t.call_summary,
            call_analysis=t.call_analysis,
            buyer_intent=t.buyer_intent,
            agent_recommendation=t.agent_recommendation,
            structured_transcript=t.structured_transcript,
            keywords=t.keywords,
            mql_assessment=t.mql_assessment,
            sentiment_analysis=t.sentiment_analysis,
            customer_rating=t.customer_rating,
            call_type=t.call_type,
            summary=t.summary,
            vehicle_tags=t.vehicle_tags,
            contact_extraction=t.contact_extraction,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to transcribe file: {e}")


async def _to_thread(func, *args, **kwargs):
    # Avoid blocking event loop with CPU/network-bound SDK calls
    try:
        import anyio

        return await anyio.to_thread.run_sync(lambda: func(*args, **kwargs))
    except Exception:
        # Fallback to asyncio
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
