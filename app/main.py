from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

import os
from dotenv import load_dotenv

# Import API router
from app.api import api_router

# Load environment variables
load_dotenv()

# Create FastAPI app
app = FastAPI(
    title="Call Transcription Analysis API",
    description="API for analyzing call transcriptions between users and agents",
    version="0.1.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Include API router
api_prefix = os.getenv("API_PREFIX", "/api/v1")
app.include_router(api_router, prefix=api_prefix)

# Custom OpenAPI and documentation endpoints

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Welcome to Call Transcription Analysis API",
        "docs": "/docs",
        "version": app.version,
    }

# Run the application
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)