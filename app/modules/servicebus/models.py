"""Models representing Service Bus payloads used by the application."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ServiceBusEnvelope:
    """Decoded Service Bus message with metadata."""

    body: Any
    properties: Optional[Dict[str, Any]]
    message_id: Optional[str]
    correlation_id: Optional[str]
    subject: Optional[str]
    content_type: Optional[str]
    enqueued_time_utc: Optional[datetime]


@dataclass(frozen=True)
class AudioProcessingMessage:
    """Expected audio processing payload produced by the Node.js webhook."""

    call_id: str
    audio_url: Optional[str]
    timestamp: Optional[str]
    ringcentral_data: Dict[str, Any]
    priority: Optional[str]
    raw: Dict[str, Any]

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "AudioProcessingMessage":
        call_id = payload.get("callId") or payload.get("call_id")
        if not call_id:
            raise ValueError("AudioProcessingMessage payload missing 'callId'")

        audio_url = payload.get("audioUrl") or payload.get("recordingUrl")
        timestamp = payload.get("timestamp")
        ringcentral_data = payload.get("ringcentralData") or payload.get("ringcentral_data") or {}
        priority = payload.get("priority")

        return cls(
            call_id=str(call_id),
            audio_url=audio_url,
            timestamp=timestamp,
            ringcentral_data=ringcentral_data if isinstance(ringcentral_data, dict) else {},
            priority=priority,
            raw=payload,
        )

    def to_payload(self) -> Dict[str, Any]:
        return dict(self.raw)
