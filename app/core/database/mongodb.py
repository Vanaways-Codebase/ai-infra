import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from app.core.config import settings

logger = logging.getLogger(__name__)


class MongoDB:
    """Simplified MongoDB connection manager."""
    
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.database: Optional[AsyncIOMotorDatabase] = None
        self.database_name: str = settings.MONGODB_DATABASE_NAME
    
    async def connect(self, connection_string: Optional[str] = None) -> None:
        """Connect to MongoDB."""
        try:
            conn_str = connection_string or settings.MONGODB_CONNECTION_STRING  
            if not conn_str:
                raise ValueError("MongoDB connection string is required")
            
            self.client = AsyncIOMotorClient(conn_str)
            await self.client.admin.command('ping')  # Test connection
            self.database = self.client[self.database_name]
            
            logger.info(f"Connected to MongoDB: {self.database_name}")
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"MongoDB connection failed: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from MongoDB."""
        if self.client:
            self.client.close()
            self.client = None
            self.database = None
            logger.info("Disconnected from MongoDB")
    
    def get_collection(self, name: str):
        """Get a collection."""
        if self.database is None:
            raise RuntimeError("Not connected to MongoDB")
        return self.database[name]


# Global instance
db = MongoDB()
