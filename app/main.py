import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.middleware import RequestLoggingMiddleware
from app.modules.servicebus.listener import ServiceBusQueueListener
from app.modules.servicebus.worker import handle_audio_processing_message

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    listener: Optional[ServiceBusQueueListener] = None
    connection = (settings.AZURE_SERVICEBUS_CONNECTION_STRING or "").strip()
    queue_name = (settings.AZURE_SERVICEBUS_QUEUE_NAME or "").strip()

    if connection and queue_name:
        listener = ServiceBusQueueListener(
            connection_string=connection,
            queue_name=queue_name,
            handler=handle_audio_processing_message,
            max_message_count=settings.AZURE_SERVICEBUS_MAX_MESSAGE_COUNT,
            max_wait_time=settings.AZURE_SERVICEBUS_MAX_WAIT_SECONDS,
        )
        await listener.start()
        logger.info("Service Bus listener started for queue '%s'", queue_name)
    else:
        logger.info("Azure Service Bus not configured; skipping listener startup")

    try:
        yield
    finally:
        if listener:
            await listener.stop()
            logger.info("Service Bus listener stopped")


app = FastAPI(
    title="Call Transcription Analysis API",
    description="API for analyzing call transcriptions between users and agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestLoggingMiddleware)

api_prefix = (settings.API_PREFIX or "/api/v1").strip() or "/api/v1"
app.include_router(api_router, prefix=api_prefix)


@app.get("/")
async def root():
    return {
        "message": "Welcome to Call Transcription Analysis API",
        "docs": "/docs",
        "version": app.version,
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
