from fastapi import APIRouter

# Import module routers
# from app.modules.transcription.routes import router as transcription_router
from app.modules.recording.routes import router as recording_router
from app.modules.asr.routes import router as asr_router

# Create main API router
api_router = APIRouter()

# Include module routers
# api_router.include_router(transcription_router, prefix="/transcription", tags=["transcription"])
api_router.include_router(recording_router, prefix="/recording", tags=["recording"])
api_router.include_router(asr_router, prefix="/asr", tags=["asr"])
# User router temporarily disabled
# from app.modules.user.routes import router as user_router
# api_router.include_router(user_router, prefix="/users", tags=["users"])
