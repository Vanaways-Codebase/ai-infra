from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime

# Base Transcription Schema
class TranscriptionBase(BaseModel):
    call_id: str = Field(..., description="Unique identifier for the call")
    user_id: Optional[int] = Field(None, description="ID of the user in the call")
    agent_id: Optional[int] = Field(None, description="ID of the agent in the call")
    duration: Optional[int] = Field(None, description="Call duration in seconds")
    content: str = Field(..., description="Full transcription text of the call")

# Create Transcription Schema
class TranscriptionCreate(TranscriptionBase):
    call_date: Optional[datetime] = Field(None, description="Date and time of the call")

# Transcription Response Schema
class TranscriptionResponse(TranscriptionBase):
    id: int
    call_date: datetime
    created_at: datetime
    updated_at: datetime

# Analysis Base Schema
class AnalysisBase(BaseModel):
    transcription_id: int = Field(..., description="ID of the transcription to analyze")

# Analysis Create Schema
class AnalysisCreate(AnalysisBase):
    pass

# Analysis Response Schema
class AnalysisResponse(BaseModel):
    id: int
    transcription_id: int
    sentiment: str
    sentiment_score: float
    rating: int
    rating_explanation: Optional[str] = None
    keywords: Dict[str, int]  # Keywords and their frequencies
    created_at: datetime
    updated_at: datetime

# Combined Transcription with Analysis Response
class TranscriptionWithAnalysis(TranscriptionResponse):
    analysis: Optional[AnalysisResponse] = None