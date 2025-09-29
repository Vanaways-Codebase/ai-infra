import json
import logging
import re
from typing import Optional, Tuple

import requests
from requests import HTTPError

from app.core.config import settings
from app.ringcentral.client import get_platform
from app.ringcentral.authtoken import get_ringcentral_access_token

logger = logging.getLogger(__name__)


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

    def _platform_get_once() -> requests.Response:
        api_response = platform.get(content_url)
        raw = api_response.response()  # underlying requests.Response
        return raw

    def _direct_get_with_token(bearer_token: str) -> requests.Response:
        headers = {"Authorization": f"Bearer {bearer_token}"}
        # Do not stream; we need headers and content immediately
        resp = requests.get(content_url, headers=headers, timeout=60)
        return resp

    # 1) Try via SDK session (uses cached token and built-in auth)
    raw: Optional[requests.Response] = None
    try:
        raw = _platform_get_once()
        if raw.status_code == 401:
            raise HTTPError(response=raw)
        raw.raise_for_status()
    except Exception as exc:
        # If unauthorized, attempt a fresh token and direct fetch
        status = getattr(getattr(exc, "response", None), "status_code", None)
        body_text = None
        try:
            body_text = getattr(getattr(exc, "response", None), "text", None)
        except Exception:
            body_text = None

        if status == 401:
            logger.warning("RingCentral 401 for media URL; attempting re-login and retry")
            try:
                # First try to refresh SDK session by logging in again with JWT
                platform.login(jwt=settings.RINGCENTRAL_JWT)
                raw = _platform_get_once()
                if raw.status_code == 401:
                    raise HTTPError(response=raw)
                raw.raise_for_status()
            except Exception:
                logger.info("SDK retry after re-login failed; attempting direct authorized fetch")
                try:
                    fresh_token = get_ringcentral_access_token(
                        settings.RINGCENTRAL_CLIENT_ID,
                        settings.RINGCENTRAL_CLIENT_SECRET,
                        settings.RINGCENTRAL_JWT,
                    )
                    raw = _direct_get_with_token(fresh_token)
                    raw.raise_for_status()
                except Exception as retry_exc:
                    # Attach context and re-raise
                    logger.error("RingCentral authorized retry failed: %s", retry_exc)
                    raise retry_exc
        else:
            # Non-401 failures: bubble up with context
            raise exc

    # If we reached here, raw is a successful response
    content_type = raw.headers.get("Content-Type", "application/octet-stream")  # type: ignore[union-attr]
    resolved_filename = _derive_filename_from_headers(
        content_url, raw.headers.get("Content-Disposition"), filename  # type: ignore[union-attr]
    )

    data = raw.content  # type: ignore[union-attr]
    return data, content_type, resolved_filename
