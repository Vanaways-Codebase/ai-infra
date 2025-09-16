# call_transcriber_app.py

import soundcard as sc
import numpy as np
import threading
import queue
import time
import io
import wave
from openai import OpenAI
import warnings
import requests
import json
from datetime import datetime, timedelta
import os

# Suppress harmless warnings from soundcard
warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)

# --- CONFIGURATION ---
SAMPLE_RATE = 48000
CHUNK_DURATION = 2  # seconds per chunk
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION)

# ==============================================================================
# CLASS 1: DUAL AUDIO TRANSCRIBER (with modifications for better control)
# ==============================================================================
class DualAudioTranscriber:
    def __init__(self, openai_api_key, status_callback=None):
        self.client = OpenAI(api_key=openai_api_key)
        self.system_audio_queue = queue.Queue(maxsize=10)
        self.mic_audio_queue = queue.Queue(maxsize=10)
        self.is_recording = False
        self.status_callback = status_callback or print # For GUI updates

        self.threads = []
        self.setup_audio_devices()

    def setup_audio_devices(self):
        try:
            default_speaker = sc.default_speaker()
            self.loopback_mic = sc.get_microphone(default_speaker.name, include_loopback=True)
            self.microphone = sc.default_microphone()
            self.status_callback(f"🔊 System audio device: {self.loopback_mic.name}")
            self.status_callback(f"🎤 Microphone device: {self.microphone.name}")
        except Exception as e:
            self.status_callback(f"❌ Error setting up audio devices: {e}")
            raise

    def audio_to_wav_bytes(self, audio_data):
        int_data = (audio_data * 32767).astype(np.int16)
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(1 if len(int_data.shape) == 1 else int_data.shape[1])
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(int_data.tobytes())
        wav_buffer.seek(0)
        return wav_buffer.getvalue()

    def _record_audio(self, device, audio_queue, source_name):
        self.status_callback(f"🔴 Starting {source_name} audio recording...")
        try:
            with device.recorder(samplerate=SAMPLE_RATE) as recorder:
                while self.is_recording:
                    audio_chunk = recorder.record(numframes=CHUNK_SIZE)
                    if self.is_recording:
                        audio_queue.put(audio_chunk)
        except Exception as e:
            if self.is_recording: # Avoid errors on normal shutdown
                 self.status_callback(f"❌ {source_name} recording error: {e}")

    def _process_transcriptions(self, audio_queue, source_name):
        self.status_callback(f"🔄 Starting {source_name} transcription processor...")
        while self.is_recording or not audio_queue.empty():
            try:
                audio_chunk = audio_queue.get(timeout=1.0)
                if np.max(np.abs(audio_chunk)) < 0.01:
                    continue

                self.status_callback(f"✍️ Transcribing {source_name} audio chunk...")
                wav_bytes = self.audio_to_wav_bytes(audio_chunk)
                audio_file = io.BytesIO(wav_bytes)
                audio_file.name = "audio.wav"

                response = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text"
                )
                transcription = response.strip()
                if transcription:
                    self.status_callback(f"[{source_name.upper()}]: {transcription}")
            except queue.Empty:
                continue
            except Exception as e:
                self.status_callback(f"❌ {source_name} processing error: {e}")

    ## MODIFIED ##: Start method now launches threads and returns immediately.
    def start_streaming(self):
        if self.is_recording:
            self.status_callback("⚠️ Already recording!")
            return
        
        self.is_recording = True
        self.status_callback("🚀 Starting dual audio transcription...")

        # Clear any old data from queues
        while not self.system_audio_queue.empty(): self.system_audio_queue.get()
        while not self.mic_audio_queue.empty(): self.mic_audio_queue.get()

        # Define and start all threads
        self.threads = [
            threading.Thread(target=self._record_audio, args=(self.loopback_mic, self.system_audio_queue, "System")),
            threading.Thread(target=self._record_audio, args=(self.microphone, self.mic_audio_queue, "Microphone")),
            threading.Thread(target=self._process_transcriptions, args=(self.system_audio_queue, "System")),
            threading.Thread(target=self._process_transcriptions, args=(self.mic_audio_queue, "Microphone"))
        ]
        
        for t in self.threads:
            t.daemon = True
            t.start()
        
        self.status_callback("✅ Transcription services are now active.")

    ## MODIFIED ##: Stop method now sets a flag and waits for threads to finish.
    def stop_streaming(self):
        if not self.is_recording:
            return
        
        self.status_callback("🛑 Stopping dual transcription...")
        self.is_recording = False
        
        # Wait for all threads to complete their current tasks and exit
        for t in self.threads:
            t.join(timeout=2.0)
            
        self.threads = []
        self.status_callback("✅ Transcription stopped!")

# ==============================================================================
# CLASS 2: RINGCENTRAL CALL MONITOR (Simplified to be a trigger)
# ==============================================================================
class RingCentralCallMonitor:
    def __init__(self, client_id, client_secret, jwt_token, server_url, status_callback=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.jwt_token = jwt_token
        self.server_url = server_url
        self.access_token = None
        self.token_expiry_time = None
        self.status_callback = status_callback or print

    def authenticate(self):
        self.status_callback("Authenticating with RingCentral...")
        url = f"{self.server_url}/restapi/oauth/token"
        headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}
        data = {'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': self.jwt_token}
        try:
            response = requests.post(url, auth=(self.client_id, self.client_secret), headers=headers, data=data, timeout=10)
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get('access_token')
                expires_in = token_data.get('expires_in', 3600)
                self.token_expiry_time = datetime.now() + timedelta(seconds=expires_in - 60)
                self.status_callback("✅ RingCentral Authentication successful.")
                return True
            else:
                self.status_callback(f"Authentication failed: {response.text}")
                return False
        except requests.RequestException as e:
            self.status_callback(f"Authentication request error: {e}")
            return False

    def refresh_token_if_needed(self):
        if not self.token_expiry_time or datetime.now() >= self.token_expiry_time:
            self.status_callback("Access token expired. Re-authenticating...")
            return self.authenticate()
        return True

    ## MODIFIED ##: This is now the core function we care about.
    def is_agent_on_call(self, agent_extension_number):
        """Checks if a specific agent extension is currently on an active call."""
        if not self.refresh_token_if_needed():
            return False

        url = f"{self.server_url}/restapi/v1.0/account/~/active-calls"
        headers = {'Authorization': f'Bearer {self.access_token}', 'Accept': 'application/json'}
        params = {'view': 'Detailed'}
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                active_calls = response.json().get('records', [])
                for call in active_calls:
                    # The call data can have the extension in multiple places
                    from_info = call.get('from', {})
                    to_info = call.get('to', {})
                    extension_info = call.get('extension', {})
                    
                    if (from_info.get('extensionNumber') == agent_extension_number or
                        to_info.get('extensionNumber') == agent_extension_number or
                        extension_info.get('extensionNumber') == agent_extension_number):
                        
                        self.status_callback(f"Call detected for agent {agent_extension_number} (Session: {call.get('sessionId')})")
                        return True # Agent found in an active call
                return False # No calls found for this agent
            else:
                self.status_callback(f"Failed to get active calls: {response.status_code} - {response.text}")
                return False
        except requests.RequestException as e:
            self.status_callback(f"Error fetching active calls: {e}")
            return False
        
# call_transcriber_app.py (continued)

import tkinter as tk
from tkinter import scrolledtext, messagebox

class AgentMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Agent Call Monitor & Transcriber")
        self.root.geometry("700x500")

        # State variables
        self.is_monitoring = False
        self.monitor_thread = None
        self.transcriber = None
        
        # --- GUI Elements ---
        main_frame = tk.Frame(root, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Input Frame
        input_frame = tk.LabelFrame(main_frame, text="Configuration", padx=10, pady=10)
        input_frame.pack(fill=tk.X, pady=5)

        tk.Label(input_frame, text="Agent Extension:").grid(row=0, column=0, sticky="w", padx=5)
        self.agent_ext_entry = tk.Entry(input_frame, width=20)
        self.agent_ext_entry.grid(row=0, column=1, padx=5)

        self.start_button = tk.Button(input_frame, text="Start Monitoring", command=self.start_monitoring, bg="#4CAF50", fg="white")
        self.start_button.grid(row=0, column=2, padx=10)

        self.stop_button = tk.Button(input_frame, text="Stop Monitoring", command=self.stop_monitoring, bg="#f44336", fg="white", state=tk.DISABLED)
        self.stop_button.grid(row=0, column=3, padx=10)

        # Status/Log Frame
        status_frame = tk.LabelFrame(main_frame, text="Live Status & Transcription", padx=10, pady=10)
        status_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.status_text = scrolledtext.ScrolledText(status_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Helvetica", 9))
        self.status_text.pack(fill=tk.BOTH, expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def update_status(self, message):
        """Safely update the GUI from any thread."""
        def callback():
            self.status_text.config(state=tk.NORMAL)
            self.status_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")
            self.status_text.config(state=tk.DISABLED)
            self.status_text.see(tk.END)
        self.root.after(0, callback)

    def start_monitoring(self):
        agent_extension = self.agent_ext_entry.get().strip()
        if not agent_extension:
            messagebox.showerror("Error", "Please enter an agent extension number.")
            return

        # Disable GUI elements
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.agent_ext_entry.config(state=tk.DISABLED)

        self.is_monitoring = True
        # Run the main logic in a separate thread to avoid freezing the GUI
        self.monitor_thread = threading.Thread(target=self.monitoring_loop, args=(agent_extension,), daemon=True)
        self.monitor_thread.start()

    def stop_monitoring(self):
        self.update_status("--- User initiated stop ---")
        self.is_monitoring = False
        
        # Enable GUI elements
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.agent_ext_entry.config(state=tk.NORMAL)
        
    def on_closing(self):
        if self.is_monitoring:
            if messagebox.askokcancel("Quit", "Monitoring is active. Do you want to stop and exit?"):
                self.stop_monitoring()
                self.root.destroy()
        else:
            self.root.destroy()

    def monitoring_loop(self, agent_extension):
        """The main loop that checks for calls and triggers transcription."""
        self.update_status(f"Starting monitoring for agent extension: {agent_extension}")
        
        # --- INITIALIZE SERVICES ---
        try:
            # RingCentral Monitor
            rc_monitor = RingCentralCallMonitor(
                client_id=os.getenv("RINGCENTRAL_CLIENT_ID"),
                client_secret=os.getenv("RINGCENTRAL_CLIENT_SECRET"),
                jwt_token=os.getenv("RINGCENTRAL_JWT_TOKEN"),
                server_url=os.environ.get("RINGCENTRAL_SERVER_URL", "https://platform.ringcentral.com"),
                status_callback=self.update_status
            )
            if not rc_monitor.authenticate():
                messagebox.showerror("Auth Error", "RingCentral authentication failed. Check credentials and logs.")
                self.stop_monitoring()
                return

            # OpenAI Transcriber
            self.transcriber = DualAudioTranscriber(
                openai_api_key=os.getenv("OPENAI_API_KEY"),
                status_callback=self.update_status
            )
        except Exception as e:
            self.update_status(f"FATAL ERROR during initialization: {e}")
            messagebox.showerror("Initialization Error", f"Could not initialize services: {e}")
            self.stop_monitoring()
            return

        is_call_active = False
        while self.is_monitoring:
            agent_is_on_call = rc_monitor.is_agent_on_call(agent_extension)

            # State Change: Call has just started
            if agent_is_on_call and not is_call_active:
                self.update_status("--- ACTIVE CALL DETECTED ---")
                is_call_active = True
                self.transcriber.start_streaming()

            # State Change: Call has just ended
            elif not agent_is_on_call and is_call_active:
                self.update_status("--- CALL ENDED ---")
                is_call_active = False
                self.transcriber.stop_streaming()
            
            # No change in state
            elif not is_call_active:
                self.update_status("...waiting for a call...")

            time.sleep(10) # Poll RingCentral every 10 seconds

        # Cleanup when loop is stopped
        if is_call_active:
            self.transcriber.stop_streaming()
        self.update_status("Monitoring has stopped.")

def main():
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()

    # Check for essential credentials
    required_vars = ["RINGCENTRAL_CLIENT_ID", "RINGCENTRAL_CLIENT_SECRET", "RINGCENTRAL_JWT_TOKEN", "OPENAI_API_KEY"]
    if not all(os.getenv(var) for var in required_vars):
        messagebox.showerror("Missing Credentials", "Please ensure all required API keys and tokens are set in your .env file.")
        return

    # Start the GUI
    root = tk.Tk()
    app = AgentMonitorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()