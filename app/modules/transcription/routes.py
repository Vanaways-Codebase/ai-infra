from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Any, Dict

from app.core.dependencies import get_groq_client
from app.modules.transcription import service as transcription_service
from app.modules.transcription.job_processor import (
    ProcessedTranscription,
    TranscriptionJobError,
    process_transcription_job,
)

router = APIRouter()


@router.post("/analyze-sentiment")
def analyze_transcription_sentiment(
    content: Dict[str, str],
    groq_client = Depends(get_groq_client),
):
    """Analyze sentiment of a transcription using Groq AI."""
    if "text" not in content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text field is required",
        )

    try:
        sentiment, sentiment_score = transcription_service.analyze_sentiment(
            groq_client, content["text"]
        )
        return {
            "sentiment": sentiment,
            "sentiment_score": sentiment_score,
        }
    except Exception as exc:  # pragma: no cover - defensive catch
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error analyzing sentiment: {exc}",
        ) from exc


@router.post("/rate-call")
def rate_transcription(
    content: Dict[str, str],
    groq_client = Depends(get_groq_client),
):
    """Rate a call transcription using Groq AI."""
    if "text" not in content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text field is required",
        )

    try:
        rating, rating_explanation = transcription_service.rate_call(
            groq_client, content["text"]
        )
        return {
            "rating": rating,
            "rating_explanation": rating_explanation,
        }
    except Exception as exc:  # pragma: no cover - defensive catch
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error rating call: {exc}",
        ) from exc


@router.post("/extract-keywords")
def extract_transcription_keywords(
    content: Dict[str, str],
    groq_client = Depends(get_groq_client),
):
    """Extract keywords from a transcription using Groq AI."""
    if "text" not in content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text field is required",
        )

    try:
        keywords = transcription_service.extract_keywords(groq_client, content["text"])
        return {"keywords": keywords}
    except Exception as exc:  # pragma: no cover - defensive catch
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error extracting keywords: {exc}",
        ) from exc


@router.post("/process-transcription")
def process_transcription_job_endpoint(
    payload: Dict[str, Any],
    groq_client = Depends(get_groq_client),
    publish_to_kafka: bool = Query(
        False, description="If true, publish result to call-update-jobs topic"
    ),
):
    """Process a transcription job (same structure as async worker messages)."""
    try:
        processed: ProcessedTranscription = process_transcription_job(
            payload,
            groq_client=groq_client,
            publish_to_kafka=publish_to_kafka,
        )
        return processed.data
    except TranscriptionJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:  # pragma: no cover - defensive catch
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Processing error: {exc}",
        ) from exc
