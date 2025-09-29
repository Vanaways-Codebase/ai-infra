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
from app.ringcentral.authtoken import (
    get_ringcentral_access_token,
    get_ringcentral_access_token_with_meta,
)

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

    - Obtains an access token via JWT credentials from settings.
    - Adds Authorization header if URL does not already include access_token.

    Returns: (data_bytes, content_type, resolved_filename)
    """
    platform = get_platform()

    def _maybe_wait_before_request():
        global _rc_next_allowed_at
        try:
            now = time.time()
            if now < _rc_next_allowed_at:
                delay = max(0.0, _rc_next_allowed_at - now)
                if delay > 0:
                    if settings.RINGCENTRAL_STRICT_RATE_LIMIT:
                        raise RingCentralRateLimitActive(delay)
                    logger.info("Delaying RingCentral request for %.2fs due to recent throttling", delay)
                    time.sleep(delay)
        except Exception:
            return

    def _platform_get_once() -> requests.Response:
        _maybe_wait_before_request()
        api_response = platform.get(content_url)
        raw = api_response.response()  # underlying requests.Response
        return raw

    def _direct_get_with_token(bearer_token: str) -> requests.Response:
        headers = {"Authorization": f"Bearer {bearer_token}"}
        # Do not stream; we need headers and content immediately
        _maybe_wait_before_request()
        resp = requests.get(content_url, headers=headers, timeout=60)
        return resp

    def _extract_rc_error_info(resp: requests.Response) -> str:
        try:
            data = resp.json()
            code = data.get("errorCode") or ""
            msg = data.get("message") or ""
            return f"{code} {msg}".strip()
        except Exception:
            return ""

    def _retry_after_seconds(resp: requests.Response, attempt: int) -> float:
        # Honor Retry-After if present, else exponential backoff with jitter
        retry_after = resp.headers.get("Retry-After") if hasattr(resp, "headers") else None
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        # RingCentral guidance: if 429 and no Retry-After, wait 30s or more
        try:
            status = int(getattr(resp, "status_code", 0))
        except Exception:
            status = 0
        if status == 429:
            return 30.0
        base = min(2 ** (attempt - 1), 16)
        return base + random.uniform(0, 0.5)

    def _maybe_pause_on_low_remaining(resp: requests.Response) -> None:
        """Implements RC guidance: if X-Rate-Limit-Remaining == 0, wait for X-Rate-Limit-Window seconds.
        Logs group and remaining for visibility. No-op if headers are absent.
        """
        try:
            headers = resp.headers or {}
            group = headers.get("X-Rate-Limit-Group")
            remaining = headers.get("X-Rate-Limit-Remaining")
            window = headers.get("X-Rate-Limit-Window")
            if remaining is None or window is None:
                return
            remaining_i = int(str(remaining).strip())
            window_s = float(str(window).strip())
            if remaining_i <= 0 and window_s > 0:
                logger.warning(
                    "RingCentral rate window exhausted (group=%s). Pausing for %.0fs",
                    group,
                    window_s,
                )
                # Set shared throttle and sleep
                global _rc_next_allowed_at
                _rc_next_allowed_at = time.time() + window_s
                if settings.RINGCENTRAL_STRICT_RATE_LIMIT:
                    return
                time.sleep(window_s)
            elif remaining_i <= 1:
                logger.info(
                    "RingCentral nearing limit (group=%s, remaining=%s, window=%s)",
                    group,
                    remaining,
                    window,
                )
        except Exception:
            # Be conservative; do not block on header parsing errors
            return

    def _get_or_refresh_direct_token(force_refresh: bool = False) -> Optional[str]:
        global _rc_cached_direct_token, _rc_cached_direct_token_expiry
        now = time.time()
        if not force_refresh and _rc_cached_direct_token:
            if _rc_cached_direct_token_expiry is None or _rc_cached_direct_token_expiry > now + 30:
                return _rc_cached_direct_token
        with _rc_token_lock:
            now = time.time()
            if not force_refresh and _rc_cached_direct_token:
                if _rc_cached_direct_token_expiry is None or _rc_cached_direct_token_expiry > now + 30:
                    return _rc_cached_direct_token
            try:
                token, expires_in = get_ringcentral_access_token_with_meta(
                    settings.RINGCENTRAL_CLIENT_ID,
                    settings.RINGCENTRAL_CLIENT_SECRET,
                    settings.RINGCENTRAL_JWT,
                )
            except Exception:
                # Fallback to legacy helper
                token = get_ringcentral_access_token(
                    settings.RINGCENTRAL_CLIENT_ID,
                    settings.RINGCENTRAL_CLIENT_SECRET,
                    settings.RINGCENTRAL_JWT,
                )
                expires_in = None
            _rc_cached_direct_token = token
            _rc_cached_direct_token_expiry = (now + float(expires_in) - 60) if expires_in else None
            return token

    def _try_platform_with_backoff(max_attempts: int = 4) -> Optional[requests.Response]:
        relogin_done = False
        last_resp: Optional[requests.Response] = None
        for attempt in range(1, max_attempts + 1):
            last_resp = _platform_get_once()
            status = last_resp.status_code
            if status == 401 and not relogin_done:
                logger.warning("RingCentral 401 via SDK; re-login and retry (attempt %d)", attempt)
                try:
                    platform.login(jwt=settings.RINGCENTRAL_JWT)
                    relogin_done = True
                    continue
                except Exception as e:
                    logger.info("SDK re-login failed: %s", e)
                    break
            if status in (429, 500, 502, 503, 504, 408):
                wait_s = _retry_after_seconds(last_resp, attempt)
                logger.warning(
                    "RingCentral transient error %s (%s). Backing off %.2fs (attempt %d/%d)",
                    status,
                    _extract_rc_error_info(last_resp),
                    wait_s,
                    attempt,
                    max_attempts,
                )
                # Share the backoff across threads in-process
                global _rc_next_allowed_at
                _rc_next_allowed_at = max(_rc_next_allowed_at, time.time() + wait_s)
                if settings.RINGCENTRAL_STRICT_RATE_LIMIT:
                    raise RingCentralRateLimitActive(wait_s)
                time.sleep(wait_s)
                continue
            try:
                last_resp.raise_for_status()
                # Update throttle on success if headers indicate zero remaining
                return last_resp
            except Exception:
                break
        return last_resp

    def _try_direct_with_backoff(max_attempts: int = 4) -> Optional[requests.Response]:
        last_resp: Optional[requests.Response] = None
        token = _get_or_refresh_direct_token(force_refresh=False)
        if not token:
            logger.error("Direct fetch aborted: could not obtain RingCentral token")
            return None
        for attempt in range(1, max_attempts + 1):
            last_resp = _direct_get_with_token(token)
            status = last_resp.status_code
            if status == 401:
                logger.warning("Direct fetch unauthorized; refreshing token and retrying (attempt %d)", attempt)
                token = _get_or_refresh_direct_token(force_refresh=True)
                if not token:
                    return last_resp
                continue
            if status in (429, 500, 502, 503, 504, 408):
                wait_s = _retry_after_seconds(last_resp, attempt)
                logger.warning(
                    "RingCentral transient error %s (%s) on direct fetch. Backing off %.2fs (attempt %d/%d)",
                    status,
                    _extract_rc_error_info(last_resp),
                    wait_s,
                    attempt,
                    max_attempts,
                )
                global _rc_next_allowed_at
                _rc_next_allowed_at = max(_rc_next_allowed_at, time.time() + wait_s)
                if settings.RINGCENTRAL_STRICT_RATE_LIMIT:
                    raise RingCentralRateLimitActive(wait_s)
                time.sleep(wait_s)
                continue
            try:
                last_resp.raise_for_status()
                return last_resp
            except Exception:
                # On other errors, let loop retry up to attempts
                pass
        return last_resp

    # 1) Try via SDK with limited backoff
    raw: Optional[requests.Response] = _try_platform_with_backoff()
    if raw is None or raw.status_code >= 400:
        logger.info("Falling back to direct authorized fetch after SDK path")
        raw = _try_direct_with_backoff()
        if raw is None:
            raise RuntimeError("RingCentral direct fetch did not return a response")
        raw.raise_for_status()

    # If we reached here, raw is a successful response
    # Courtesy pause if remaining hits 0 per RC guidance
    _maybe_pause_on_low_remaining(raw)

    content_type = raw.headers.get("Content-Type", "application/octet-stream")  # type: ignore[union-attr]
    resolved_filename = _derive_filename_from_headers(
        content_url, raw.headers.get("Content-Disposition"), filename  # type: ignore[union-attr]
    )

    data = raw.content  # type: ignore[union-attr]
    return data, content_type, resolved_filename
