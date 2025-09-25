import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings(BaseSettings):
    # API Settings
    API_VERSION: str = os.getenv("API_VERSION", "v1")
    API_PREFIX: str = os.getenv("API_PREFIX", f"/api/{API_VERSION}")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    # Database Settings
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")
    
    # Groq API Settings
    # Read GROQ_API_KEY and strip surrounding quotes if present (some .env files include quotes)
    GROQ_API_KEY: str = (os.getenv("GROQ_API_KEY", "") or "").strip().strip('"').strip("'")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama3-70b-8192")
    
    # Security Settings
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))


    KAFKA_BROKERS: str = os.getenv("KAFKA_BROKERS", "localhost:9092")
    KAFKA_CLIENT_ID: str = os.getenv("KAFKA_CLIENT_ID", "vims-backend")
    KAFKA_GROUP_ID: str = os.getenv("KAFKA_GROUP_ID", "vims-transcription-workers")
    KAFKA_TRANSCRIPTION_TOPIC: str = os.getenv("KAFKA_TRANSCRIPTION_TOPIC", "transcription-jobs")
    KAFKA_CALL_UPDATE_TOPIC: str = os.getenv("KAFKA_CALL_UPDATE_TOPIC", "call-update-jobs")

    RINGCENTRAL_CLIENT_ID: str = os.getenv("RINGCENTRAL_CLIENT_ID", "")
    RINGCENTRAL_CLIENT_SECRET: str = os.getenv("RINGCENTRAL_CLIENT_SECRET", "")
    RINGCENTRAL_JWT: str = os.getenv("RINGCENTRAL_JWT", "")

    # Azure Event Hubs
    AZURE_EVENTHUB_CONNECTION_STRING: str = os.getenv("AZURE_EVENTHUB_CONNECTION_STRING", "")
    AZURE_EVENTHUB_NAME: str = os.getenv("AZURE_EVENTHUB_NAME", "")
    AZURE_EVENTHUB_CONSUMER_GROUP: str = os.getenv("AZURE_EVENTHUB_CONSUMER_GROUP", "$Default")
    AZURE_EVENTHUB_PREFETCH: int = int(os.getenv("AZURE_EVENTHUB_PREFETCH", "300"))

    # Azure Service Bus
    AZURE_SERVICEBUS_CONNECTION_STRING: str = os.getenv("AZURE_SERVICEBUS_CONNECTION_STRING", "")
    AZURE_SERVICEBUS_QUEUE_NAME: str = os.getenv("AZURE_SERVICEBUS_QUEUE_NAME", "")
    AZURE_SERVICEBUS_MAX_MESSAGE_COUNT: int = int(os.getenv("AZURE_SERVICEBUS_MAX_MESSAGE_COUNT", "5"))
    AZURE_SERVICEBUS_MAX_WAIT_SECONDS: float = float(os.getenv("AZURE_SERVICEBUS_MAX_WAIT_SECONDS", "5"))

    # OpenAI Settings
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")    
    OPENAI_TRANSCRIPTION_MODEL: str = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
    OPENAI_INSIGHTS_MODEL: str = os.getenv("OPENAI_INSIGHTS_MODEL", "gpt-4o-mini")
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

# Create settings instance
settings = Settings()
