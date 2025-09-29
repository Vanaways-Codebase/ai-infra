import logging

# FastAPI imports
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# API imports
from app.api import api_router

# Core imports
from app.core.config import settings
from app.core.lifespan import lifespan

# Middleware imports
from app.middleware import RequestLoggingMiddleware

# Logging configuration
logger = logging.getLogger(__name__)


def create_application() -> FastAPI:
    application = FastAPI(
        title="TapTap AI Infrastructure",
        description="AI Infrastructure with Service Bus Integration",
        version="1.0.0",
        lifespan=lifespan
    )
    
    # Add your routes here
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.add_middleware(RequestLoggingMiddleware)
    application.include_router(api_router, prefix=settings.API_PREFIX or "/api/v1")


    
    return application

app = create_application()

@app.get("/", tags=["App"], summary="App Version")
async def root():
    return {
        "message": "AI Infra is running!",
        "version": "29a",
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
