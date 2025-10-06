import asyncio
import logging
import time
from typing import Optional, Callable, Any
from collections import deque

logger = logging.getLogger(__name__)


class WhisperRateLimiter:
    """Rate limiter specifically for Azure OpenAI Whisper with 3 RPM quota."""
    
    def __init__(self, requests_per_minute: int = 3):
        """
        Initialize rate limiter for Whisper API.
        
        Args:
            requests_per_minute: Maximum requests allowed per minute (default: 3)
        """
        self.requests_per_minute = requests_per_minute
        self.request_times = deque(maxlen=requests_per_minute)
        self.lock = asyncio.Lock()
        
    async def acquire(self):
        """
        Acquire permission to make a request.
        Will wait if necessary to stay within rate limits.
        """
        async with self.lock:
            now = time.time()
            
            # If we haven't made enough requests yet, allow immediately
            if len(self.request_times) < self.requests_per_minute:
                self.request_times.append(now)
                logger.debug(f"Rate limiter: {len(self.request_times)}/{self.requests_per_minute} requests used")
                return
            
            # Check the oldest request time
            oldest_request = self.request_times[0]
            time_since_oldest = now - oldest_request
            
            # If oldest request was less than 60 seconds ago, we need to wait
            if time_since_oldest < 60:
                wait_time = 60 - time_since_oldest + 0.5  # Add 0.5s buffer
                logger.info(
                    f"⏳ Rate limit: {self.requests_per_minute} requests used. "
                    f"Waiting {wait_time:.1f}s before next request..."
                )
                await asyncio.sleep(wait_time)
            
            # Record this request
            self.request_times.append(time.time())
            logger.debug(f"Rate limiter: Request allowed. Window resets in 60s")
    
    def reset(self):
        """Reset the rate limiter."""
        self.request_times.clear()
        logger.info("Rate limiter reset")


# Global rate limiter instance
whisper_rate_limiter = WhisperRateLimiter(requests_per_minute=3)