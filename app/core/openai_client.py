from functools import lru_cache
from openai import OpenAI
from app.core.config import settings

# Cached OpenAI client instance
# Using LRU cache to ensure a single instance (get_openai_client) is reused
@lru_cache(maxsize=1)
def get_openai_client() -> OpenAI:
    api_key = (settings.OPENAI_API_KEY or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    return OpenAI(api_key=api_key)
