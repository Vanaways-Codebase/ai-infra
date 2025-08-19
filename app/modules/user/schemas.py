from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime

from app.modules.user.models import UserRole

# Base User Schema
class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    full_name: Optional[str] = None
    role: Optional[UserRole] = UserRole.USER

# User Create Schema
class UserCreate(UserBase):
    password: str = Field(..., min_length=8)

# User Update Schema
class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)
    is_active: Optional[bool] = None

# User Response Schema
class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

# Token Schema
class Token(BaseModel):
    access_token: str
    token_type: str

# Token Data Schema
class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None