import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.asr import service as asr_service


def test_build_structured_entries_splits_agent_customer_blocks():
    items = [
        {
            "message": "Agent: Hello there\nCustomer: Hi!\nAgent: How can I help today?",
        }
    ]

    structured = asr_service._build_structured_entries(items)
    assert len(structured) == 3
    assert [entry["speaker"] for entry in structured] == ["agent", "customer", "agent"]
    assert structured[0]["message"].startswith("Hello")


def test_build_structured_entries_splits_newlines_without_speaker():
    items = [
        {
            "speaker": "customer",
            "message": "First line\nSecond line",
        }
    ]

    structured = asr_service._build_structured_entries(items)
    assert len(structured) == 2
    assert all(entry["speaker"] == "customer" for entry in structured)
    assert [entry["message"] for entry in structured] == ["First line", "Second line"]
