import asyncio
import sys
import types
from typing import Dict

import pytest


class _ServiceBusMessageStub:
    def __init__(self, *, body, application_properties=None, message_id="mid-1"):
        self.body = body
        self.application_properties = application_properties or {}
        self.message_id = message_id
        self.correlation_id = None
        self.subject = None
        self.content_type = "application/json"
        self.enqueued_time_utc = None


class _ServiceBusClientStub:
    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def from_connection_string(cls, conn_str: str):
        return cls()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get_queue_receiver(self, *args, **kwargs):  # pragma: no cover - defensive
        raise RuntimeError("Receiver not implemented in test stub")

    def get_queue_sender(self, *args, **kwargs):  # pragma: no cover - defensive
        raise RuntimeError("Sender not implemented in test stub")


class _ServiceBusOutgoingMessageStub:
    def __init__(self, *args, **kwargs):
        self.body = kwargs.get("body") if kwargs else (args[0] if args else None)
        self.application_properties = kwargs.get("application_properties")
        self.message_id = kwargs.get("message_id")
        self.content_type = kwargs.get("content_type")
        self.subject = kwargs.get("subject")


if "azure.servicebus" not in sys.modules:
    azure_pkg = sys.modules.setdefault("azure", types.ModuleType("azure"))
    servicebus_mod = types.ModuleType("servicebus")
    aio_mod = types.ModuleType("servicebus_aio")

    servicebus_mod.ServiceBusReceivedMessage = _ServiceBusMessageStub
    servicebus_mod.ServiceBusMessage = _ServiceBusOutgoingMessageStub
    aio_mod.ServiceBusClient = _ServiceBusClientStub

    servicebus_mod.aio = aio_mod
    azure_pkg.servicebus = servicebus_mod

    sys.modules["azure.servicebus"] = servicebus_mod
    sys.modules["azure.servicebus.aio"] = aio_mod

if "groq" not in sys.modules:
    groq_mod = types.ModuleType("groq")

    class _GroqStub:
        def __init__(self, *args, **kwargs):
            pass

    groq_mod.Groq = _GroqStub
    sys.modules["groq"] = groq_mod

from app.modules.servicebus.listener import ServiceBusQueueListener
from app.modules.servicebus.models import AudioProcessingMessage, ServiceBusEnvelope
from app.modules.servicebus.worker import handle_audio_processing_message


def _loop_run(coro):
    return asyncio.run(coro)


def test_decode_body_json():
    message = _ServiceBusMessageStub(body=[b"{\"hello\": \"world\"}"])
    decoded = ServiceBusQueueListener._decode_body(message)  # type: ignore[arg-type]
    assert decoded == {"hello": "world"}


def test_decode_body_plain_text():
    message = _ServiceBusMessageStub(body=[b"plain text"])
    decoded = ServiceBusQueueListener._decode_body(message)  # type: ignore[arg-type]
    assert decoded == "plain text"


def test_audio_processing_message_from_payload():
    payload: Dict[str, object] = {
        "callId": "123",
        "audioUrl": "https://example.com/audio.mp3",
        "timestamp": "2024-01-01T00:00:00Z",
        "ringcentralData": {"foo": "bar"},
        "priority": "high",
    }
    message = AudioProcessingMessage.from_payload(payload)
    assert message.call_id == "123"
    assert message.audio_url == "https://example.com/audio.mp3"
    assert message.ringcentral_data == {"foo": "bar"}


def test_handle_audio_processing_message_invokes_processor(monkeypatch):
    envelope = ServiceBusEnvelope(
        body={"callId": "456"},
        properties=None,
        message_id="mid-123",
        correlation_id=None,
        subject=None,
        content_type="application/json",
        enqueued_time_utc=None,
    )

    called = {}

    def _fake_process(payload):
        called["processed"] = payload
        class _Result:
            data = payload
        return _Result()

    monkeypatch.setattr(
        "app.modules.servicebus.worker.process_transcription_job",
        _fake_process,
    )
    monkeypatch.setattr(
        "app.modules.servicebus.worker.dump_processed_transcription",
        lambda result: "{}",
    )

    _loop_run(handle_audio_processing_message(envelope))

    assert called["processed"] == {"callId": "456"}


def test_handle_audio_processing_message_skips_non_dict(caplog):
    envelope = ServiceBusEnvelope(
        body="not-a-dict",
        properties=None,
        message_id="mid-skip",
        correlation_id=None,
        subject=None,
        content_type="text/plain",
        enqueued_time_utc=None,
    )

    caplog.set_level("WARNING")
    _loop_run(handle_audio_processing_message(envelope))
    assert any("non-dict" in record.message for record in caplog.records)
