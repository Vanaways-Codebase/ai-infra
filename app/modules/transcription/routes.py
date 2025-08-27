from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, List, Any, Optional
import groq
from app.core.dependencies import get_groq_client
from app.modules.transcription.service import (
    analyze_sentiment,
    rate_call,
    extract_keywords,
    get_client_details,
    make_transcription_readable,
)
from app.kafka_consumer import download_audio, transcribe_audio, get_kafka_producer
from app.core.config import settings
from dotenv import load_dotenv
import os 

load_dotenv()
router = APIRouter()

@router.post("/analyze-sentiment")
def analyze_transcription_sentiment(
    content: Dict[str, str],
    groq_client = Depends(get_groq_client)
):
    """Analyze sentiment of a transcription using Groq AI"""
    if "text" not in content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text field is required"
        )
    
    try:
        sentiment, sentiment_score = analyze_sentiment(groq_client, content["text"])
        
        return {
            "sentiment": sentiment,
            "sentiment_score": sentiment_score
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error analyzing sentiment: {str(e)}"
        )

@router.post("/rate-call")
def rate_transcription(
    content: Dict[str, str],
    groq_client = Depends(get_groq_client)
):
    """Rate a call transcription using Groq AI"""
    if "text" not in content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text field is required"
        )
    
    try:
        rating, rating_explanation = rate_call(groq_client, content["text"])
        
        return {
            "rating": rating,
            "rating_explanation": rating_explanation
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error rating call: {str(e)}"
        )

@router.post("/extract-keywords")
def extract_transcription_keywords(
    content: Dict[str, str],
    groq_client = Depends(get_groq_client)
):
    """Extract keywords from a transcription using Groq AI"""
    if "text" not in content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text field is required"
        )
    
    try:
        keywords = extract_keywords(groq_client, content["text"])
        
        return {
            "keywords": keywords
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error extracting keywords: {str(e)}"
        )


@router.post("/process-transcription")
def process_transcription_job_endpoint(
    payload: Dict[str, Any],
    groq_client = Depends(get_groq_client),
    publish_to_kafka: Optional[bool] = Query(False, description="If true, publish result to call-update-jobs topic")
):
    """
    Process a transcription job (same structure as Kafka message).
    Accepts either a `recordingUrl` (will be downloaded and transcribed) or `call_transcript` (already-transcribed text).
    Returns the analysis payload identical to what the Kafka worker would publish.
    """
    call_id = payload.get("callId") or payload.get("call_id")
    recording_url = payload.get("recordingUrl") or payload.get("recording_url")
    call_transcript = payload.get("call_transcript") or payload.get("transcript") or None
    meta = payload.get("meta", {})

    if not call_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="callId is required")

    if not call_transcript and not recording_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'call_transcript' or 'recordingUrl' must be provided"
        )

    try:

        groq_client=groq.Groq(api_key=os.getenv("api_key"))
        # If recording URL provided, download and transcribe
        if not call_transcript and recording_url:
            audio_path = download_audio(recording_url)
            if not audio_path:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to download audio")
            call_transcript = transcribe_audio(groq_client, audio_path)
            if not call_transcript:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Transcription failed")
        
        # Run analyses
        sentiment, sentiment_score = analyze_sentiment(groq_client, call_transcript)
        rating, rating_explanation = rate_call(groq_client, call_transcript)
        keywords = extract_keywords(groq_client, call_transcript)

        client_details = get_client_details(groq_client, call_transcript)
        email = client_details.get("email", "")
        name = client_details.get("name", "")

        formatted_transcript = make_transcription_readable(groq_client, call_transcript)

        response_payload = {
            "callId": call_id,
            "sentiment": sentiment,
            "sentiment_score": sentiment_score,
            "keywords": keywords,
            "call_rating": rating,
            "rating_explanation": rating_explanation,
            "client_email": email,
            "client_name": name,
            "call_transcript": call_transcript,
            "formatted_transcript": formatted_transcript,
            "meta": meta,
        }

        # Optionally publish to Kafka (best-effort; failures do not change HTTP response)
        if publish_to_kafka:
            try:
                producer = get_kafka_producer()
                if producer:
                    producer.send(settings.KAFKA_CALL_UPDATE_TOPIC, value=response_payload)
                    producer.flush()
            except Exception:
                # make endpoint resilient; do not raise on Kafka failures
                pass

        return response_payload

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Processing error: {str(e)}")


