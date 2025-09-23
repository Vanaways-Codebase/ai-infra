import requests, re
from typing import Optional, Tuple

from app.ringcentral.client import get_platform


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

    - Obtains an access token via JWT credentials from settings.
    - Adds Authorization header if URL does not already include access_token.

    Returns: (data_bytes, content_type, resolved_filename)
    """
    platform = get_platform()
    api_response = platform.get(content_url)

    # api_response.response() returns underlying requests.Response
    raw = api_response.response()
    raw.raise_for_status()

    content_type = raw.headers.get("Content-Type", "application/octet-stream")
    resolved_filename = _derive_filename_from_headers(content_url, raw.headers.get("Content-Disposition"), filename)

    data = raw.content
    return data, content_type, resolved_filename
