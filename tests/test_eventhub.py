import json
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest


class _EventDataStub:
    def __init__(self, body: bytes):
        self._body = body
        self.properties = {}

    def body_as_str(self, encoding: str = "utf-8") -> str:
        return self._body.decode(encoding)


class _EventDataBatchStub:
    def __init__(self):
        self.events = []

    def add(self, event: _EventDataStub) -> None:
        self.events.append(event)

    def __len__(self) -> int:
        return len(self.events)


class _ProducerStub:
    instances = []

    def __init__(self, *args, **kwargs):
        self.batches = []
        self.closed = False

    @classmethod
    def from_connection_string(cls, conn_str: str, eventhub_name: str):
        instance = cls(conn_str, eventhub_name)
        cls.instances.append(instance)
        return instance

    def create_batch(self):
        return _EventDataBatchStub()

    def send_batch(self, batch: _EventDataBatchStub) -> None:
        self.batches.append(list(batch.events))

    def close(self) -> None:
        self.closed = True


class _ConsumerStub:
    instances = []
    events_to_return = []

    def __init__(self, *args, **kwargs):
        self.closed = False

    @classmethod
    def from_connection_string(cls, conn_str: str, consumer_group: str, eventhub_name: str, prefetch: int):
        instance = cls(conn_str, consumer_group, eventhub_name, prefetch)
        cls.instances.append(instance)
        return instance

    def get_partition_ids(self):
        return ["0"]

    def receive_batch(self, partition_id: str, max_batch_size: int, max_wait_time: float):
        return self.events_to_return[:max_batch_size]

    def close(self) -> None:
        self.closed = True


# Inject azure.eventhub stub if the real package is not available.
if "azure.eventhub" not in sys.modules:
    azure_pkg = sys.modules.setdefault("azure", types.ModuleType("azure"))
    eventhub_stub = types.ModuleType("eventhub")
    eventhub_stub.EventData = _EventDataStub
    eventhub_stub.EventHubProducerClient = _ProducerStub
    eventhub_stub.EventHubConsumerClient = _ConsumerStub
    azure_pkg.eventhub = eventhub_stub
    sys.modules["azure.eventhub"] = eventhub_stub

import app.modules.eventhub.service as eventhub_service
from app.modules.eventhub.service import EventHubClient, EventHubMessage

eventhub_service.EventData = _EventDataStub
eventhub_service.EventHubProducerClient = _ProducerStub
eventhub_service.EventHubConsumerClient = _ConsumerStub


@pytest.fixture(autouse=True)
def _reset_stubs():
    _ProducerStub.instances.clear()
    _ConsumerStub.instances.clear()
    _ConsumerStub.events_to_return = []
    yield
    _ProducerStub.instances.clear()
    _ConsumerStub.instances.clear()
    _ConsumerStub.events_to_return = []


def test_send_and_receive_roundtrip(monkeypatch):
    monkeypatch.setenv("AZURE_EVENTHUB_CONNECTION_STRING", "Endpoint=sb://example.servicebus.windows.net/;SharedAccessKeyName=test;SharedAccessKey=dummy")
    monkeypatch.setenv("AZURE_EVENTHUB_NAME", "sample-hub")
    monkeypatch.setattr(eventhub_service.settings, "AZURE_EVENTHUB_CONNECTION_STRING", "Endpoint=sb://example.servicebus.windows.net/;SharedAccessKeyName=test;SharedAccessKey=dummy", raising=False)
    monkeypatch.setattr(eventhub_service.settings, "AZURE_EVENTHUB_NAME", "sample-hub", raising=False)

    client = EventHubClient()
    message = EventHubMessage(body={"hello": "world"}, properties={"custom": "meta"})

    client.send(message)
    producer = _ProducerStub.instances[-1]
    assert len(producer.batches) == 1
    sent_event = producer.batches[0][0]
    assert json.loads(sent_event.body_as_str()) == {"hello": "world"}
    assert sent_event.properties["custom"] == "meta"

    sent_event.properties["origin"] = "unit-test"
    _ConsumerStub.events_to_return = producer.batches[0]

    received = client.receive_batch(partition_id="0", max_events=5)
    assert len(received) == 1
    assert received[0].body == {"hello": "world"}
    assert received[0].properties == {"custom": "meta", "origin": "unit-test"}

    partitions = client.list_partitions()
    assert partitions == ["0"]

    client.close()
    assert producer.closed is True
    consumer = _ConsumerStub.instances[-1]
    assert consumer.closed is True
