import asyncio
import logging
import warnings
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.services.azure.service_bus import ServiceBusManager
from app.core.config import settings
from app.core.database.mongodb import db

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress CosmosDB compatibility warnings
# warnings.filterwarnings("ignore", message=".*CosmosDB cluster.*", category=UserWarning)

# Global service bus manager instance
service_bus_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global service_bus_manager
    
    # Startup
    logger.info("🔌 Connecting to MongoDB...", extra={'tag': 'lifecycle'})
    await db.connect()

    logger.info("🚀 Starting Service Bus Manager...")
    service_bus_manager = ServiceBusManager()
    
    # Start listening to queues in background
    await service_bus_manager.start()
    
    yield
    
    # Shutdown
    logger.info("🔌 Disconnecting from MongoDB...")
    await db.disconnect()
    
    logger.info("🛑 Shutting down Service Bus Manager...")
    if service_bus_manager:
        await service_bus_manager.stop()