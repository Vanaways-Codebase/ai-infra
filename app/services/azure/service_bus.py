import asyncio
import json
import time
from typing import Optional

from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio import ServiceBusClient

from app.core.config import settings


class ServiceBusManager:
    """Minimal async Service Bus manager without threading or extra complexity."""

    def __init__(self) -> None:
        self.client: Optional[ServiceBusClient] = None
        self.running: bool = False
        self.tasks: list[asyncio.Task] = []
        self.queue_names: list[str] = ["audio-processing-queue"]

    async def start(self) -> None:
        """Initialize the client and start non-blocking listeners."""
        try:
            self.client = ServiceBusClient.from_connection_string(
                settings.AZURE_SERVICEBUS_CONNECTION_STRING
            )
            self.running = True

            for queue in self.queue_names:
                self.tasks.append(asyncio.create_task(self._listen_to_queue(queue)))

            print("Service Bus Manager started")
        except Exception as e:
            print(f"Failed to start Service Bus Manager: {e}")
            raise

    async def _listen_to_queue(self, queue_name: str) -> None:
        if not self.client:
            print("Service Bus client not initialized")
            return

        try:
            receiver = self.client.get_queue_receiver(queue_name=queue_name)
            async with receiver:
                while self.running:
                    try:
                        messages = await receiver.receive_messages(
                            max_message_count=10,
                            max_wait_time=5,
                        )
                        for msg in messages:
                            await self._process_message(msg, queue_name, receiver)
                    except Exception as e:
                        if self.running:
                            print(f"Error receiving from {queue_name}: {e}")
        except Exception as e:
            print(f"Failed to setup listener for {queue_name}: {e}")

    async def _process_message(self, msg, queue_name: str, receiver) -> None:
        try:
            body_bytes = b"".join(part for part in msg.body)
            body = body_bytes.decode("utf-8", errors="replace")
            print(f"Received from {queue_name}: {body}")

            if queue_name == "audio-processing-queue":
                await self._process_audio_message(body, receiver, msg)
            else:
                await receiver.complete_message(msg)
        except Exception as e:
            print(f"Error processing message from {queue_name}: {e}")
            try:
                await receiver.complete_message(msg)
            except Exception:
                pass

    async def _process_audio_message(self, body: str, receiver, msg) -> None:
        lock_task: Optional[asyncio.Task] = None
        try:
            data = json.loads(body)
            audio_url = data.get("audio_url")
            ring_central_id = data.get("ring_central_id")

            if not audio_url:
                print(f"No audio URL provided for: {ring_central_id}")
                await receiver.complete_message(msg)
                return

            print(f"Processing RingCentral audio from URL: {audio_url}")

            from app.modules.asr.routes import _build_transcribe_response
            from app.modules.asr.service import transcribe
            from app.modules.recording.service import RingCentralRateLimitActive

            try:
                lock_task = asyncio.create_task(
                    self._renew_lock_periodically(receiver, msg)
                )
                transcription_result = await transcribe(url=str(audio_url))
                response_data = _build_transcribe_response(
                    transcription_result, ring_central_id=ring_central_id
                )

                processed = response_data.model_dump()
                encoded = json.dumps(processed).encode("utf-8")
                await self.send_message(encoded, "audio-response-queue")
                await receiver.complete_message(msg)
            except RingCentralRateLimitActive as rate_limit_error:
                retry_after = getattr(rate_limit_error, "retry_after", 30)
                print(
                    f"RingCentral rate limit active for url={audio_url}. Retry after {retry_after:.0f}s."
                )
                await receiver.complete_message(msg)
            except Exception as transcription_error:
                print(f"Transcription failed for url={audio_url}: {transcription_error}")
                await receiver.complete_message(msg)
        except Exception as e:
            print(f"Error processing audio: {e}")
            try:
                await receiver.complete_message(msg)
            except Exception:
                pass
        finally:
            await self._cancel_lock_task(lock_task)

    async def send_message(self, message: bytes, queue_name: str) -> None:
        if not self.client or not self.running:
            print("Service Bus client not available")
            return
        try:
            sender = self.client.get_queue_sender(queue_name=queue_name)
            async with sender:
                sb_message = ServiceBusMessage(message)
                await sender.send_messages(sb_message)
                print(f"Sent to {queue_name}: {message.decode('utf-8', errors='replace')}")
        except Exception as e:
            print(f"Error sending message to {queue_name}: {e}")

    async def stop(self) -> None:
        print("Stopping Service Bus Manager...")
        self.running = False

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

        if self.client:
            try:
                await self.client.close()
                print("Service Bus client closed")
            except Exception as e:
                print(f"Error closing Service Bus client: {e}")

        print("Service Bus Manager stopped")

    async def _renew_lock_periodically(self, receiver, msg, *, interval: int = 10, timeout: int = 600):
        start = time.monotonic()
        try:
            while True:
                try:
                    await receiver.renew_message_lock(msg)
                except Exception as exc:
                    print(f"Failed to renew lock for message: {exc}")
                    return
                if 0 < timeout <= time.monotonic() - start:
                    return
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise

    async def _cancel_lock_task(self, task: Optional[asyncio.Task]) -> None:
        if task is None:
            return
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
