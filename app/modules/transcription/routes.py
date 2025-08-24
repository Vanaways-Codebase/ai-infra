from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, List, Any

from app.core.dependencies import get_groq_client
from app.modules.transcription.service import analyze_sentiment, rate_call, extract_keywords

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


