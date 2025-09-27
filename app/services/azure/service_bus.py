# import time, threading, json
# from app.core.config import settings

# from azure.servicebus import ServiceBusClient, ServiceBusReceiver, ServiceBusMessage
# def receive_messages(queue_name: str):
#     sb_client = ServiceBusClient.from_connection_string(settings.AZURE_SERVICEBUS_CONNECTION_STRING)
#     receiver = sb_client.get_queue_receiver(queue_name=queue_name, max_message_size_in_kb=5000)

#     while True:
#         try:
#             messages = receiver.receive_messages(max_wait_time=5, max_message_count=10)
#             for msg in messages:
#                 # Extract the message body by iterating the generator and decoding
#                 body = b''.join(msg.body).decode('utf-8')  # Combine generator output and decode
#                 print(f"Received: {body}")  # Process your data here (e.g., save to DB)
#                 receiver.complete_message(msg)  # Acknowledge the message

#                 dummy_message = {"message": "DummyMessage"}
#                 encoded_message = json.dumps(dummy_message).encode("utf-8")
#                 send_new_message(encoded_message, "audio-response-queue")
                
#         except Exception as e:
#             print(f"Error receiving: {e}")
#         time.sleep(1)  # Poll interval


# def send_new_message(message: str, queue_name: str):
#     sb_client = ServiceBusClient.from_connection_string(settings.AZURE_SERVICEBUS_CONNECTION_STRING)
#     sender = sb_client.get_queue_sender(queue_name=queue_name)
#     with sender:
#         single_message = ServiceBusMessage(message)
#         sender.send_messages(single_message)
#         print(f"Sent: {message}")
# System-aware configuration  
import os
import psutil
import concurrent.futures
import time
import threading
import json
import asyncio
from typing import Optional
from app.core.config import settings
from azure.servicebus import ServiceBusClient, ServiceBusReceiver, ServiceBusMessage

class ServiceBusManager:
    def __init__(self):
        self.client: Optional[ServiceBusClient] = None
        self.receivers = {}
        self.running = False
        self.threads = []
        self.cpu_count = os.cpu_count() or 1
        self.max_workers = min(32, (self.cpu_count + 4))  # Azure best practice
        self.max_memory_percent = 85.0
        self.executor = None
        self.active_tasks = 0
        self.task_lock = threading.Lock()
        
    async def start(self):
        """Initialize Service Bus client and start message processing"""
        try:
            self.client = ServiceBusClient.from_connection_string(
                settings.AZURE_SERVICEBUS_CONNECTION_STRING
            )
            self.running = True

            # Initialize thread pool with system-aware configuration
            self.executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=self.max_workers,
                thread_name_prefix="ServiceBus"
)
            
            # Start listening to your queues
            await self._start_queue_listeners()
            print("Service Bus Manager started successfully")
            
        except Exception as e:
            print(f"Failed to start Service Bus Manager: {e}")
            raise
    
    async def _start_queue_listeners(self):
        """Start background threads for queue listeners"""
        # Add your queue names here
        queue_names = ["audio-processing-queue"]
        
        for queue_name in queue_names:
            thread = threading.Thread(
                target=self._listen_to_queue,
                args=(queue_name,),
                daemon=True
            )
            thread.start()
            self.threads.append(thread)
    
    def _listen_to_queue(self, queue_name: str):
        """Listen to a specific queue in a separate thread"""
        try:
            receiver = self.client.get_queue_receiver(
                queue_name=queue_name, 
                max_message_size_in_kb=5000
            )
            self.receivers[queue_name] = receiver
            
            while self.running:
                try:
                    messages = receiver.receive_messages(
                        max_wait_time=5, 
                        max_message_count=10
                    )
                    
                    # Process messages in parallel using thread pool
                    futures = []
                    for msg in messages:
                        if self.running and self._can_process_more():
                            future = self.executor.submit(
                                self._process_message_wrapper, 
                                msg, queue_name, receiver
                            )
                            futures.append(future)
                        else:
                            # Process synchronously if system is under pressure
                            self._process_message_sync(msg, queue_name, receiver)
                        
                except Exception as e:
                    if self.running:  # Only log if we're still supposed to be running
                        print(f"Error receiving from {queue_name}: {e}")
                
                if self.running:
                    time.sleep(1)
                    
        except Exception as e:
            print(f"Failed to setup listener for {queue_name}: {e}")
    
    def _process_message_wrapper(self, msg, queue_name: str, receiver):
        """Thread-safe wrapper for async message processing"""
        with self.task_lock:
            self.active_tasks += 1
        
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                loop.run_until_complete(self._process_message_async(msg, queue_name, receiver))
            finally:
                loop.close()
                
        except Exception as e:
            print(f"Error in message wrapper for {queue_name}: {e}")
            try:
                receiver.complete_message(msg)
            except:
                pass
        finally:
            with self.task_lock:
                self.active_tasks -= 1

    async def _process_message_async(self, msg, queue_name: str, receiver):
        """Process individual messages asynchronously"""
        try:
            body = b''.join(msg.body).decode('utf-8')
            print(f"[Thread-{threading.current_thread().name}] Received from {queue_name}: {body}")
            
            if queue_name == "audio-processing-queue":
                await self._process_audio_message(body, receiver, msg)
            else:
                receiver.complete_message(msg)
                
        except Exception as e:
            print(f"Error processing message from {queue_name}: {e}")
            try:
                receiver.complete_message(msg)
            except:
                pass
    
    async def _process_audio_message(self, body: str, receiver, msg):
        """Process audio transcription message asynchronously"""
        try:
            # Parse the incoming message to get the audio URL
            message_data = json.loads(body)
            audio_url = message_data.get('audio_url')
            ring_central_id = message_data.get('ring_central_id')
            
            if not audio_url:
                print(f"No audio URL provided for: {ring_central_id}")
                receiver.complete_message(msg)
                # Don't send error response, just complete and log
                return
            
            print(f"[Thread-{threading.current_thread().name}] Processing RingCentral audio from URL: {audio_url}")
            
            # Import the transcription functions
            from app.modules.asr.routes import _to_thread, _transcribe_ringcentral_content, _build_transcribe_response
            from app.modules.asr.service import transcribe_from_url
            
            try:
                # Primary transcription attempt using RingCentral-specific logic
                transcription_result = await _to_thread(_transcribe_ringcentral_content, str(audio_url))
                response_data = _build_transcribe_response(transcription_result, ring_central_id=ring_central_id)
                
                # Only send response on SUCCESS
                processed_response = response_data.model_dump()
                encoded_response = json.dumps(processed_response).encode("utf-8")
                self.send_message(encoded_response, "audio-response-queue")
                receiver.complete_message(msg)
                
            except Exception as primary_error:
                print(f"RingCentral download failed for url={audio_url}: {primary_error}")
                
                try:
                    # Fallback transcription attempt
                    transcription_result = await _to_thread(transcribe_from_url, str(audio_url))
                    response_data = _build_transcribe_response(transcription_result, ring_central_id=ring_central_id)
                    
                    # Only send response on SUCCESS
                    processed_response = response_data.model_dump()
                    encoded_response = json.dumps(processed_response).encode("utf-8")
                    self.send_message(encoded_response, "audio-response-queue")
                    receiver.complete_message(msg)
                    
                except Exception as fallback_error:
                    print(f"Fallback transcription failed for url={audio_url}: {fallback_error}")
                    # Don't send error response, just complete the message and log
                    receiver.complete_message(msg)
                
        except Exception as e:
            print(f"Error processing audio: {str(e)}")
            # Don't send error response, just complete the message
            try:
                receiver.complete_message(msg)
            except:
                pass
    def _can_process_more(self) -> bool:
        """Check if system can handle more parallel tasks"""
        try:
            memory_percent = psutil.virtual_memory().percent
            
            # Check active tasks count
            with self.task_lock:
                if self.active_tasks >= self.max_workers:
                    return False
            
            # Check memory usage
            if memory_percent > self.max_memory_percent:
                return False
            
            return True
            
        except Exception:
            return self.active_tasks < self.max_workers // 2  # Conservative fallback

    def _process_message_sync(self, msg, queue_name: str, receiver):
        """Synchronous message processing fallback when system is under pressure"""
        try:
            body = b''.join(msg.body).decode('utf-8')
            print(f"\n[SYNC] Received from {queue_name}: {body}")
            
            if queue_name == "audio-processing-queue":
                # For sync processing, just complete the message without sending response
                try:
                    message_data = json.loads(body)
                    print(f"[SYNC] Audio processing skipped due to system load for: {message_data.get('ring_central_id')}")
                    receiver.complete_message(msg)
                    # Don't send any response - just acknowledge and skip
                    
                except Exception as e:
                    print(f"Error in sync processing: {e}")
                    # Don't send error response, just complete the message
                    try:
                        receiver.complete_message(msg)
                    except:
                        pass
            else:
                receiver.complete_message(msg)
                
        except Exception as e:
            print(f"Error in sync processing for {queue_name}: {e}")
            # Don't send error response, just complete the message
            try:
                receiver.complete_message(msg)
            except:
                pass


    def send_message(self, message: bytes, queue_name: str):
        """Send a message to specified queue"""
        if not self.client or not self.running:
            print("Service Bus client not available")
            return
            
        try:
            sender = self.client.get_queue_sender(queue_name=queue_name)
            with sender:
                service_bus_message = ServiceBusMessage(message)
                sender.send_messages(service_bus_message)
                print(f"Sent to {queue_name}") #{message.decode('utf-8')}
                
        except Exception as e:
            print(f"Error sending message to {queue_name}: {e}")
    
    async def stop(self):
        """Stop all listeners and close connections"""
        print("Stopping Service Bus Manager...")
        self.running = False

        # Shutdown thread pool executor gracefully
        if self.executor:
            print("Shutting down thread pool executor...")
            self.executor.shutdown(wait=True)
                
        # Close all receivers
        for queue_name, receiver in self.receivers.items():
            try:
                receiver.close()
                print(f"Closed receiver for {queue_name}")
            except Exception as e:
                print(f"Error closing receiver for {queue_name}: {e}")
        
        # Wait for threads to finish (with timeout)
        for thread in self.threads:
            thread.join(timeout=5)
        
        # Close the main client
        if self.client:
            try:
                self.client.close()
                print("Service Bus client closed")
            except Exception as e:
                print(f"Error closing Service Bus client: {e}")
        
        print("Service Bus Manager stopped")

# Legacy functions for backward compatibility
def receive_messages(queue_name: str):
    """Deprecated: Use ServiceBusManager instead"""
    print("Warning: receive_messages is deprecated. Use ServiceBusManager instead.")

def send_new_message(message: str, queue_name: str):
    """Deprecated: Use ServiceBusManager.send_message instead"""
    print("Warning: send_new_message is deprecated. Use ServiceBusManager.send_message instead.")