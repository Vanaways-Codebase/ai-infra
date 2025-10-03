from functools import lru_cache
from openai import OpenAI, AzureOpenAI
from app.core.config import settings

# Cached OpenAI client instance
# Using LRU cache to ensure a single instance (get_openai_client) is reused
@lru_cache(maxsize=1)
def get_openai_client() -> OpenAI:
    api_key = (settings.OPENAI_API_KEY or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    return OpenAI(api_key=api_key)


@lru_cache(maxsize=1)
def get_azure_openai_client():
    """
    Initialize and return the Azure OpenAI client.
    
    Returns:
        AzureOpenAI: Configured Azure OpenAI client
    """
    client = AzureOpenAI(
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION or "2024-12-01-preview",
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT
    )
    return client

@lru_cache(maxsize=1)
def get_azure_openai_eastus_client():
    """
    Initialize and return the Azure OpenAI client for East US deployment.
    
    Returns:
        AzureOpenAI: Configured Azure OpenAI client for East US
    """
    client = AzureOpenAI(
        api_key=settings.AZURE_OPENAI_EASTUS_API_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION or "2024-12-01-preview",
        azure_endpoint=settings.AZURE_OPENAI_EASTUS_ENDPOINT
    )
    return client