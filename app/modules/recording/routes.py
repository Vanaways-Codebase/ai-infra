from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .schemas import DownloadRequest
from .service import fetch_recording_bytes


router = APIRouter()


@router.post("/download", response_class=StreamingResponse, summary="Download a RingCentral audio file by content URL")
def download_recording(body: DownloadRequest):
    try:
        data, content_type, filename = fetch_recording_bytes(str(body.content_url), body.filename)

        headers = {"Content-Disposition": f"attachment; filename={filename}"}
        return StreamingResponse(iter([data]), media_type=content_type, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download recording: {e}")

