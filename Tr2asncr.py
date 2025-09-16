import soundcard as sc
import numpy as np
import threading
import queue
import time
import io
import wave
from openai import OpenAI
import warnings
# Configuration
SAMPLE_RATE = 48000
CHUNK_DURATION = 2  # seconds per chunk
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION)
warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)
class DualAudioTranscriber:
    def __init__(self, openai_api_key):
        """Initialize the dual audio transcriber with OpenAI client."""
        self.client = OpenAI(api_key=openai_api_key)
        
        # Separate queues for different audio sources
        self.system_audio_queue = queue.Queue()
        self.mic_audio_queue = queue.Queue()
        
        self.is_recording = False
        
        # Get audio devices
        self.setup_audio_devices()
        
    def setup_audio_devices(self):
        """Setup system audio (loopback) and microphone devices."""
        try:
            # System audio (what's playing on speakers)
            default_speaker = sc.default_speaker()
            self.loopback_mic = sc.get_microphone(
                default_speaker.name, 
                include_loopback=True
            )
            print(f"🔊 System audio device: {self.loopback_mic.name}")
            
            # Microphone input
            self.microphone = sc.default_microphone()
            print(f"🎤 Microphone device: {self.microphone.name}")
            
            # Debug: List all available microphones
            print("\n📋 Available microphones:")
            all_mics = sc.all_microphones()
            for i, mic in enumerate(all_mics):
                marker = "👈 DEFAULT" if mic.name == self.microphone.name else ""
                print(f"   {i+1}. {mic.name} {marker}")
            
            print(f"\n🔧 Using microphone: {self.microphone.name}")
            
        except Exception as e:
            print(f"❌ Error setting up audio devices: {e}")
            raise
    
    def audio_to_wav_bytes(self, audio_data):
        """Convert numpy audio data to WAV format bytes."""
        # Convert to 16-bit integers
        int_data = (audio_data * 32767).astype(np.int16)
        
        # Create WAV file in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1 if len(int_data.shape) == 1 else int_data.shape[1])
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(int_data.tobytes())
        
        wav_buffer.seek(0)
        return wav_buffer.getvalue()
    
    def record_system_audio(self):
        """Record system audio in chunks and add to system queue."""
        print(f"🔴 Starting SYSTEM audio recording...")
        
        with self.loopback_mic.recorder(samplerate=SAMPLE_RATE) as recorder:
            while self.is_recording:
                try:
                    # Record a chunk of system audio
                    audio_chunk = recorder.record(numframes=CHUNK_SIZE)
                    
                    # Add to system audio queue
                    if not self.system_audio_queue.full():
                        self.system_audio_queue.put(audio_chunk)
                    else:
                        print("⚠️  System audio queue full, dropping chunk")
                        
                except Exception as e:
                    print(f"❌ System audio recording error: {e}")
                    break
    
    def record_microphone_audio(self):
        """Record microphone audio in chunks and add to mic queue."""
        print(f"🔴 Starting MICROPHONE audio recording...")
        
        with self.microphone.recorder(samplerate=SAMPLE_RATE) as recorder:
            while self.is_recording:
                try:
                    # Record a chunk of microphone audio
                    audio_chunk = recorder.record(numframes=CHUNK_SIZE)
                    
                    # Add to microphone audio queue
                    if not self.mic_audio_queue.full():
                        self.mic_audio_queue.put(audio_chunk)
                    else:
                        print("⚠️  Microphone audio queue full, dropping chunk")
                        
                except Exception as e:
                    print(f"❌ Microphone recording error: {e}")
                    break
    
    def transcribe_audio_chunk(self, audio_data):
        """Send audio chunk to OpenAI for transcription."""
        try:
            # Convert audio to WAV bytes
            wav_bytes = self.audio_to_wav_bytes(audio_data)
            
            # Create a file-like object for OpenAI API
            audio_file = io.BytesIO(wav_bytes)
            audio_file.name = "audio.wav"  # OpenAI needs a filename
            
            # Call OpenAI Whisper API
            response = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
            
            return response.strip()
            
        except Exception as e:
            print(f"❌ Transcription error: {e}")
            return None
    
    def process_system_audio_transcriptions(self):
        """Process system audio chunks from queue and transcribe them."""
        print("🔄 Starting SYSTEM audio transcription processor...")
        
        while self.is_recording or not self.system_audio_queue.empty():
            try:
                # Get system audio chunk from queue
                audio_chunk = self.system_audio_queue.get(timeout=1.0)
                
                # Skip if audio is too quiet (avoid transcribing silence)
                if np.max(np.abs(audio_chunk)) < 0.01:
                    continue
                
                print("🔊 Transcribing SYSTEM audio chunk...")
                transcription = self.transcribe_audio_chunk(audio_chunk)
                
                if transcription:
                    print(f"🔊 [SYSTEM AUDIO]: {transcription}")
                    print("-" * 50)
                else:
                    print("🔇 [SYSTEM AUDIO]: No transcription (silence)")
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ System audio processing error: {e}")
    
    def process_microphone_transcriptions(self):
        """Process microphone audio chunks from queue and transcribe them."""
        print("🔄 Starting MICROPHONE transcription processor...")
        
        while self.is_recording or not self.mic_audio_queue.empty():
            try:
                # Get microphone audio chunk from queue
                audio_chunk = self.mic_audio_queue.get(timeout=1.0)
                
                # Skip if audio is too quiet (avoid transcribing silence)
                if np.max(np.abs(audio_chunk)) < 0.01:
                    continue
                
                print("🎤 Transcribing MICROPHONE audio chunk...")
                transcription = self.transcribe_audio_chunk(audio_chunk)
                
                if transcription:
                    print(f"🎤 [MICROPHONE]: {transcription}")
                    print("-" * 50)
                else:
                    print("🔇 [MICROPHONE]: No transcription (silence)")
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ Microphone processing error: {e}")
    
    def start_streaming(self):
        """Start real-time dual audio streaming and transcription."""
        if self.is_recording:
            print("⚠️  Already recording!")
            return
        
        self.is_recording = True
        
        print("🚀 Starting dual audio transcription...")
        print("🔊 System Audio: What's playing on your speakers")
        print("🎤 Microphone: Your voice input")
        print("=" * 60)
        
        # Start system audio recording thread
        system_recording_thread = threading.Thread(target=self.record_system_audio)
        system_recording_thread.daemon = True
        system_recording_thread.start()
        
        # Start microphone recording thread
        mic_recording_thread = threading.Thread(target=self.record_microphone_audio)
        mic_recording_thread.daemon = True
        mic_recording_thread.start()
        
        # Start system audio transcription processing thread
        system_transcription_thread = threading.Thread(target=self.process_system_audio_transcriptions)
        system_transcription_thread.daemon = True
        system_transcription_thread.start()
        
        # Start microphone transcription processing thread
        mic_transcription_thread = threading.Thread(target=self.process_microphone_transcriptions)
        mic_transcription_thread.daemon = True
        mic_transcription_thread.start()
        
        print("✅ Dual audio transcription started!")
        print("Press Ctrl+C to stop...")
        print("=" * 60)
        
        try:
            # Keep main thread alive
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Stopping dual transcription...")
            self.stop_streaming()
    
    def stop_streaming(self):
        """Stop audio streaming and transcription."""
        self.is_recording = False
        print("✅ Dual transcription stopped!")

def main():
    """Main function to run the dual audio transcriber."""
    # You need to set your OpenAI API key here
    OPENAI_API_KEY = ""
    if OPENAI_API_KEY == "your-openai-api-key-here":
        print("❌ Please set your OpenAI API key in the OPENAI_API_KEY variable")
        return
    
    try:
        # Create and start the dual transcriber
        transcriber = DualAudioTranscriber(OPENAI_API_KEY)
        transcriber.start_streaming()
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()