"""Reusable dependency providers for FastAPI routes."""

from functools import lru_cache

import groq

from app.core.config import settings


@lru_cache(maxsize=1)
def _create_groq_client() -> groq.Groq:
    api_key = (settings.GROQ_API_KEY or "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    return groq.Groq(api_key=api_key)


def get_groq_client() -> groq.Groq:
    """FastAPI dependency that returns a cached Groq client."""
    return _create_groq_client()
