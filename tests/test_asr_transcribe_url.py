import sys
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "groq" not in sys.modules:
    import types

    groq_mod = types.ModuleType("groq")

    class _GroqStub:
        def __init__(self, *args, **kwargs):
            pass

    groq_mod.Groq = _GroqStub
    sys.modules["groq"] = groq_mod

from app.main import app
from app.modules.asr.service import TranscriptionResult


def test_transcribe_url_uses_ringcentral(monkeypatch):
    monkeypatch.setattr(  # disable service bus listener during test
        "app.main.settings.AZURE_SERVICEBUS_CONNECTION_STRING",
        "",
        raising=False,
    )
    monkeypatch.setattr(
        "app.main.settings.AZURE_SERVICEBUS_QUEUE_NAME",
        "",
        raising=False,
    )

    result = TranscriptionResult(
        status="completed",
        text="transcribed",
        confidence=0.9,
    )

    monkeypatch.setattr(
        "app.modules.asr.routes._transcribe_ringcentral_content",
        lambda url: result,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/asr/transcribe/url",
        json={"audio_url": "https://rc.example.com/content/123"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "transcribed"
    assert payload["status"].lower() == "completed"
