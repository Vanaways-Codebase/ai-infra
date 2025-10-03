import json
import logging
import re
import time
import random
import threading
from dataclasses import dataclass
from typing import Optional, Tuple

import requests
from requests import HTTPError

from app.core.config import settings
from app.ringcentral.client import get_platform


logger = logging.getLogger(__name__)

# Module-level soft throttle shared within process
_rc_next_allowed_at: float = 0.0
_rc_token_lock = threading.Lock()
_rc_cached_direct_token: Optional[str] = None
_rc_cached_direct_token_expiry: Optional[float] = None  # epoch seconds


@dataclass
class RingCentralRateLimitActive(Exception):
    retry_after: float
    message: str = "RingCentral rate limit active"
    def __str__(self) -> str:
        return f"{self.message}; retry after {self.retry_after:.0f}s"


def _derive_filename_from_headers(url: str, content_disposition: Optional[str], fallback: Optional[str]) -> str:
    if fallback:
        return fallback

    if content_disposition:
        match = re.search(r'filename\*=UTF-8\'\'([^;]+)|filename="?([^";]+)"?', content_disposition)
        if match:
            return requests.utils.unquote(match.group(1) or match.group(2))

    # Fallback: take last part of URL path
    path_part = url.split("?")[0].rstrip("/")
    candidate = path_part.split("/")[-1] or "recording"
    if "." not in candidate:
        candidate += ".mp3"
    return candidate


def fetch_recording_bytes(content_url: str, filename: Optional[str] = None) -> Tuple[bytes, str, str]:
    """
    Download a RingCentral recording given a content URL.
    Returns: (data_bytes, content_type, resolved_filename)
    """
    try:
        platform = get_platform()
        api_response = platform.get(content_url)
        return api_response.response()
    except Exception as e:
        logger.error(f"Failed to fetch recording from {content_url}: {e}")
        raise
        
