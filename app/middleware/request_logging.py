import json
import logging
import time
from typing import Any, Dict, Tuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


LOG_METHODS = {"POST", "PUT", "DELETE"}
logger = logging.getLogger("app.middleware.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request/response data for mutating HTTP methods."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        method = request.method.upper()
        if method not in LOG_METHODS:
            return await call_next(request)

        start_time = time.perf_counter()
        request_body, body_bytes = await self._extract_body(request)
        logger.info(
            "Incoming %s %s query=%s body=%s",
            method,
            request.url.path,
            dict(request.query_params),
            request_body,
        )

        response = await call_next(request)

        response_body, response_bytes = await self._extract_response_body(response)
        elapsed = time.perf_counter() - start_time
        duration_ms = elapsed * 1000
        duration_min = elapsed / 60
        logger.info(
            "Completed %s %s status=%s duration_ms=%.2f duration_min=%.4f body=%s",
            method,
            request.url.path,
            response.status_code,
            duration_ms,
            duration_min,
            response_body,
        )

        headers = dict(response.headers)
        headers.pop("content-length", None)
        new_response = Response(
            content=response_bytes,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
        new_response.background = response.background
        return new_response

    async def _extract_body(self, request: Request) -> Tuple[Any, bytes]:
        content_type = request.headers.get("content-type", "")
        if "multipart" in content_type:
            return "<multipart omitted>", b""

        try:
            body_bytes = await request.body()
            if not body_bytes:
                return None, b""

            async def receive() -> Dict[str, Any]:
                return {"type": "http.request", "body": body_bytes, "more_body": False}

            request._receive = receive  # type: ignore[attr-defined]
            return self._safe_json(body_bytes), body_bytes
        except Exception as exc:
            logger.debug("Failed to read request body: %s", exc)
            return None, b""

    async def _extract_response_body(self, response: Response) -> Tuple[Any, bytes]:
        body_chunks = []
        try:
            async for chunk in response.body_iterator:
                body_chunks.append(chunk)
        except Exception as exc:
            logger.debug("Failed to read response body: %s", exc)

        body_bytes = b"".join(body_chunks)
        parsed_body: Any = self._safe_json(body_bytes) if body_bytes else None
        return parsed_body, body_bytes

    def _safe_json(self, body: bytes) -> Any:
        if not body:
            return None
        trimmed = body[:4096]
        try:
            return json.loads(trimmed)
        except json.JSONDecodeError:
            try:
                return trimmed.decode("utf-8", errors="replace")
            except Exception:
                return "<binary>"
