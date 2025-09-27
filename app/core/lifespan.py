import asyncio
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.services.azure.service_bus import ServiceBusManager
from app.core.config import settings

# Global service bus manager instance
service_bus_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global service_bus_manager
    
    # Startup
    print("Starting Service Bus Manager...")
    service_bus_manager = ServiceBusManager()
    
    # Start listening to queues in background
    await service_bus_manager.start()
    
    yield
    
    # Shutdown
    print("Shutting down Service Bus Manager...")
    if service_bus_manager:
        await service_bus_manager.stop()