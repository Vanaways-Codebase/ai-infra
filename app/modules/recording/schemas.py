from pydantic import BaseModel, HttpUrl
from typing import Optional


class DownloadRequest(BaseModel):
    content_url: HttpUrl
    filename: Optional[str] = None


class DownloadResponse(BaseModel):
    filename: str
    content_type: str
    size_bytes: int

