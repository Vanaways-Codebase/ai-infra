from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.core.dependencies import Base

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"
    AGENT = "agent"

class User(Base):
    """User model for authentication and identification"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    full_name = Column(String, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.USER)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    user_transcriptions = relationship("Transcription", foreign_keys="[Transcription.user_id]", back_populates="user")
    agent_transcriptions = relationship("Transcription", foreign_keys="[Transcription.agent_id]", back_populates="agent")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)