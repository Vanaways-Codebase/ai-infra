from pydantic import BaseModel, HttpUrl
from typing import Any, Dict, List, Literal, Optional


class TranscribeUrlRequest(BaseModel):
    audio_url: HttpUrl


class TranscriptUtterance(BaseModel):
    speaker: Literal["agent", "customer"]
    message: str
    timestamp: Dict[str, str]


class TranscribeResponse(BaseModel):
    status: str
    text: str
    confidence: Optional[float] = None
    id: Optional[str] = None
    call_summary: Optional[str] = None
    call_analysis: Optional[str] = None
    buyer_intent: Optional[str] = None
    agent_recommendation: Optional[str] = None
    structured_transcript: Optional[List[TranscriptUtterance]] = None
    keywords: Optional[List[str]] = None
    mql_assessment: Optional[float] = None
    sentiment_analysis: Optional[float] = None
    customer_rating: Optional[float] = None
    call_type: Optional[str] = None
    summary: Optional[str] = None
    vehicle_tags: Optional[Dict[str, str]] = None
    contact_extraction: Optional[Dict[str, str]] = None
