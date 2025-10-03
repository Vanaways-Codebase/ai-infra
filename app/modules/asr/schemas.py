from typing import Any, Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl


class TranscribeUrlRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    audio_url: HttpUrl = Field(validation_alias=AliasChoices("audio_url", "audioUrl"))
    ring_central_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("ring_central_id", "ringCentralId"),
    )


class AudioProcessingMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    audio_url: HttpUrl = Field(validation_alias=AliasChoices("audio_url", "audioUrl"))
    ring_central_id: str = Field(validation_alias=AliasChoices("ring_central_id", "ringCentralId"))
    timestamp: Optional[str] = None


class TranscriptUtterance(BaseModel):
    speaker: Literal["agent", "customer"]
    message: str
    timestamp: Dict[str, str]


class ContactExtraction(BaseModel):
    """Contact information extracted from the call."""
    name: Optional[str] = None
    email: Optional[str] = Field(default=None, pattern=r'^[^@]+@[^@]+\.[^@]+$')
    phone: Optional[str] = None
    company: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None


class TranscribeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ring_central_id: Optional[str] = Field(default=None, serialization_alias="ringCentralId")
    rating: float = Field(default=0)
    call_type: str = Field(default="", serialization_alias="callType")
    mql_score: float = Field(default=0, serialization_alias="mqlScore")
    sentiment_score: float = Field(default=0, serialization_alias="sentimentScore")
    keywords: List[str] = Field(default_factory=list)
    transcription: List[TranscriptUtterance] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    summary: str = Field(default="")
    call_analysis: Optional[str] = Field(default=None, serialization_alias="callAnalysis")
    buyer_intent: float = Field(default=0, serialization_alias="buyerIntent")
    buyer_intent_reason: Optional[str] = Field(default=None, serialization_alias="buyerIntentReason")
    agent_recommendation: Optional[str] = Field(default=None, serialization_alias="agentRecommendation")
    contact_extraction: ContactExtraction = Field(
        default_factory=ContactExtraction,
        serialization_alias="contactExtraction",
    )

    def model_dump(self, *args, **kwargs) -> Dict[str, Any]:  # type: ignore[override]
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)


# Add to your schemas.py file
class TranscribeIdRequest(BaseModel):
    """Request model for transcribing audio using a RingCentral recording ID."""
    recording_id: str


class TranscriptionResult(BaseModel):
    """Result model for transcription with call analysis."""
    model_config = ConfigDict(populate_by_name=True)
    
    status: str
    text: str
    confidence: Optional[float] = None
    id: Optional[str] = None
    call_summary: Optional[str] = Field(default=None, serialization_alias="summary")
    call_analysis: Optional[str] = Field(default=None, serialization_alias="analysis")
    buyer_intent: Optional[str] = None
    buyer_intent_score: Optional[float] = None
    buyer_intent_reason: Optional[str] = None
    agent_recommendation: Optional[str] = None
    structured_transcript: Optional[List[Dict[str, Any]]] = None
    keywords: Optional[List[str]] = Field(default_factory=list)
    mql_assessment: Optional[float] = Field(default=None, serialization_alias="mql_score")
    sentiment_analysis: Optional[float] = Field(default=None, serialization_alias="sentiment")
    customer_rating: Optional[float] = Field(default=None, serialization_alias="rating")
    call_type: Optional[str] = None
    summary: Optional[str] = None
    vehicle_tags: Optional[Dict[str, str]] = Field(default=None, serialization_alias="tags")
    contact_extraction: Optional[ContactExtraction] = Field(default=None, serialization_alias="contacts")

    def model_dump(self, *args, **kwargs) -> Dict[str, Any]:  # type: ignore[override]
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)
