from app.core.config import settings

# Groq client dependency
def get_groq_client():
    """Dependency for getting Groq client"""
    import groq
    
    # Initialize Groq client
    client = groq.Groq(api_key=settings.GROQ_API_KEY)
    
    return client