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
    contact_extraction: Optional[Dict[str, str]] = Field(default=None, serialization_alias="contactExtraction")

    def model_dump(self, *args, **kwargs) -> Dict[str, Any]:  # type: ignore[override]
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)
