from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
import threading
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv
from app.api import api_router
from app.kafka_consumer import consume_messages

# Import API router
from app.api import api_router

# Load environment variables
load_dotenv()



def run_kafka_consumer():
    """Wrapper function to run the Kafka consumer."""
    print("Starting Kafka consumer in a background thread...")
    consume_messages()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup, run the Kafka consumer in a daemon thread
    consumer_thread = threading.Thread(target=run_kafka_consumer, daemon=True)
    consumer_thread.start()
    yield
    # On shutdown
    print("Shutting down application.")

# Create FastAPI app
app = FastAPI(
    title="Call Transcription Analysis API",
    description="API for analyzing call transcriptions between users and agents",
    version="0.1.0",
    lifespan=lifespan
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
# def run_kafka_consumer():
#     """Wrapper function to run the Kafka consumer."""
#     print("Starting Kafka consumer in a background thread...")
#     consume_messages()

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # On startup, run the Kafka consumer in a daemon thread
#     consumer_thread = threading.Thread(target=run_kafka_consumer, daemon=True)
#     consumer_thread.start()
#     yield
#     # On shutdown
#     print("Shutting down application.")


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