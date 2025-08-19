from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.dependencies import Base

class Transcription(Base):
    """Model for storing call transcriptions"""
    __tablename__ = "transcriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    agent_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    call_id = Column(String, unique=True, index=True)
    call_date = Column(DateTime, default=datetime.utcnow)
    duration = Column(Integer)  # Call duration in seconds
    
    # Transcription content
    content = Column(Text)  # Full transcription text
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="user_transcriptions")
    agent = relationship("User", foreign_keys=[agent_id], back_populates="agent_transcriptions")
    analysis = relationship("TranscriptionAnalysis", back_populates="transcription", uselist=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TranscriptionAnalysis(Base):
    """Model for storing transcription analysis results"""
    __tablename__ = "transcription_analyses"
    
    id = Column(Integer, primary_key=True, index=True)
    transcription_id = Column(Integer, ForeignKey("transcriptions.id"), unique=True)
    
    # Sentiment analysis
    sentiment = Column(String)  # positive, negative, neutral
    sentiment_score = Column(Float)  # Score between -1 and 1
    
    # Call rating
    rating = Column(Integer)  # Rating out of 10
    rating_explanation = Column(Text, nullable=True)  # Explanation for the rating
    
    # Keywords extraction
    keywords = Column(JSON)  # JSON object with keywords and their frequencies
    
    # Relationships
    transcription = relationship("Transcription", back_populates="analysis")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)