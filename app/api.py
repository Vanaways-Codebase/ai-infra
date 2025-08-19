from fastapi import APIRouter

# Import module routers
from app.modules.transcription.routes import router as transcription_router

# Create main API router
api_router = APIRouter()

# Include module routers
api_router.include_router(transcription_router, prefix="/transcription", tags=["transcription"])
# User router temporarily disabled
# from app.modules.user.routes import router as user_router
# api_router.include_router(user_router, prefix="/users", tags=["users"])