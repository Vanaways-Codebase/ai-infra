import requests
import websocket
import json
import time
from datetime import datetime, timedelta
import threading
import wave
import base64
import os
from dotenv import load_dotenv
load_dotenv()

class RingCentralCallMonitor:
    def __init__(self, client_id, client_secret, jwt_token, server_url="https://platform.ringcentral.com"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.jwt_token = jwt_token
        self.server_url = server_url
        self.access_token = None
        self.token_expiry_time = None
        self.supervisor_device_id = None
        self.monitored_sessions = set()
        self.lock = threading.Lock()

    def authenticate(self):
        """Authenticate using JWT and get access token."""
        print("Authenticating...")
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
                print(f"Authentication successful. Token is valid until {self.token_expiry_time.strftime('%Y-%m-%d %H:%M:%S')}")
                return True
            else:
                print(f"Authentication failed: {response.status_code} - {response.text}")
                return False
        except requests.RequestException as e:
            print(f"Authentication request error: {e}")
            return False

    def select_supervisor_device(self):
        """Fetches available devices and sets the supervisor_device_id."""
        if not self.access_token:
            print("Cannot select a device without being authenticated.")
            return False

        print("\nFetching available supervisor devices...")
        url = f"{self.server_url}/restapi/v1.0/account/~/extension/~/device"
        headers = {'Authorization': f'Bearer {self.access_token}', 'Accept': 'application/json'}
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                print(f"Failed to get device list: {response.status_code} - {response.text}")
                return False

            devices = response.json().get('records', [])
            if not devices:
                print("Error: No devices found for this extension. Cannot proceed with supervision.")
                return False

            # Attempt to automatically select a SoftPhone
            softphones = [d for d in devices if d.get('type') == 'SoftPhone']
            if len(softphones) == 1:
                self.supervisor_device_id = softphones[0]['id']
                print(f"✅ Automatically selected SoftPhone: {softphones[0].get('name')} (ID: {self.supervisor_device_id})")
                return True

            # If no clear choice, prompt the user
            print("Please choose a device to use for supervision:")
            for i, device in enumerate(devices):
                print(f"  [{i + 1}] {device.get('name')} (Type: {device.get('type')}, ID: {device.get('id')})")
            
            while True:
                try:
                    choice = int(input(f"Enter number (1-{len(devices)}): ")) - 1
                    if 0 <= choice < len(devices):
                        chosen_device = devices[choice]
                        self.supervisor_device_id = chosen_device['id']
                        print(f"✅ Using device: {chosen_device.get('name')} (ID: {self.supervisor_device_id})")
                        return True
                    else:
                        print("Invalid number. Please try again.")
                except ValueError:
                    print("Invalid input. Please enter a number.")

        except requests.RequestException as e:
            print(f"Error fetching devices: {e}")
            return False

    def refresh_token_if_needed(self):
        """Check if the token has expired and re-authenticate if it has."""
        if not self.token_expiry_time or datetime.now() >= self.token_expiry_time:
            print("Access token expired or is missing. Re-authenticating...")
            return self.authenticate()
        return True

    def get_active_calls(self):
        """Fetches real-time active calls for the entire account."""
        if not self.refresh_token_if_needed(): 
            return None

        # ✅ FIXED: Using the correct active-calls endpoint
        url = f"{self.server_url}/restapi/v1.0/account/~/active-calls"
        
        headers = {'Authorization': f'Bearer {self.access_token}', 'Accept': 'application/json'}
        
        try:
            # Request detailed view to get all necessary information
            params = {'view': 'Detailed'}
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                active_calls = data.get('records', [])
                if active_calls:
                    print(f"Found {len(active_calls)} active call(s)")
                return active_calls
            else:
                print(f"Failed to get active calls: {response.status_code} - {response.text}")
                # If you get 404, the endpoint might not be available for your account type
                if response.status_code == 404:
                    print("Note: The active-calls endpoint may not be available for your account. Check account permissions.")
                return None
                
        except requests.RequestException as e:
            print(f"Error fetching active calls: {e}")
            return None

    def supervise_call(self, telephony_session_id, agent_extension_id):
        """Start supervising a call to get audio stream."""
        if not self.refresh_token_if_needed(): 
            return None
            
        url = f"{self.server_url}/restapi/v1.0/account/~/telephony/sessions/{telephony_session_id}/supervise"
        headers = {'Authorization': f'Bearer {self.access_token}', 'Content-Type': 'application/json'}
        
        # Convert agent_extension_id to string if it's an integer
        agent_extension_id_str = str(agent_extension_id)
        
        data = {
            'mode': 'Listen',
            'supervisorDeviceId': self.supervisor_device_id,
            'agentExtensionId': agent_extension_id_str,  # Ensure it's a string
            'media': True
        }
        
        print(f"Attempting to supervise session: {telephony_session_id} for agent: {agent_extension_id_str}")
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            if response.status_code == 200:
                print(f"[{telephony_session_id}] Call supervision started successfully.")
                return response.json()
            else:
                print(f"[{telephony_session_id}] Failed to supervise call: {response.status_code} - {response.text}")
                
                # Provide more specific error guidance
                if "CMN-101" in response.text and "agentExtensionId" in response.text:
                    print(f"[{telephony_session_id}] The agent extension ID '{agent_extension_id_str}' is invalid.")
                    print(f"[{telephony_session_id}] Make sure the agent is currently on this call and you have supervision permissions.")
                elif "SUP-106" in response.text:
                    print(f"[{telephony_session_id}] Supervision is not allowed. Check account permissions.")
                
                return None
        except requests.RequestException as e:
            print(f"[{telephony_session_id}] Error during supervision request: {e}")
            return None

    def start_audio_stream_listener(self, ws_url, access_token, session_id):
        """WebSocket listener for audio stream."""
        audio_data = []
        
        def save_audio_file():
            if not audio_data: 
                return
            filename = f"call_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
            print(f"[{session_id}] Saving audio to {filename}...")
            try:
                with wave.open(filename, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(8000)
                    wf.writeframes(b''.join(audio_data))
                print(f"[{session_id}] Audio saved successfully.")
            except Exception as e: 
                print(f"[{session_id}] Error saving audio: {e}")

        def on_message(ws, msg):
            try:
                data = json.loads(msg)
                if data.get('type') == 'audio' and data.get('data'):
                    audio_data.append(base64.b64decode(data['data']))
                elif data.get('type') == 'error':
                    print(f"[{session_id}] Stream error: {data.get('message', 'Unknown error')}")
            except Exception as e: 
                print(f"[{session_id}] Message processing error: {e}")
                
        def on_error(ws, error): 
            print(f"[{session_id}] WebSocket error: {error}")
            
        def on_close(ws, code, msg):
            print(f"[{session_id}] WebSocket closed. Code: {code}, Message: {msg}")
            save_audio_file()
            with self.lock: 
                self.monitored_sessions.discard(session_id)
                
        def on_open(ws):
            print(f"[{session_id}] WebSocket opened. Authenticating stream...")
            ws.send(json.dumps({"type": "auth", "token": access_token}))

        ws_app = websocket.WebSocketApp(
            ws_url, 
            on_open=on_open, 
            on_message=on_message, 
            on_error=on_error, 
            on_close=on_close
        )
        ws_app.run_forever()

    def start_monitoring_loop(self):
        """The main loop to poll for active calls and start monitoring them."""
        if not self.supervisor_device_id:
            print("Cannot start monitoring loop without a supervisor device ID.")
            return

        print("\n" + "="*50)
        print("CALL MONITORING SERVICE STARTED")
        print("="*50)
        print(f"Supervisor Device ID: {self.supervisor_device_id}")
        print("Polling for active calls every 10 seconds...")
        print("Press Ctrl+C to stop\n")
        
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while True:
            try:
                active_calls = self.get_active_calls()
                
                if active_calls is None:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        print(f"Too many consecutive errors ({max_consecutive_errors}). Stopping monitor.")
                        break
                    print(f"Error getting active calls (attempt {consecutive_errors}/{max_consecutive_errors})")
                    time.sleep(30)
                    continue
                
                consecutive_errors = 0  # Reset error counter on success
                
                if active_calls:
                    for call in active_calls:
                        # Get session ID
                        session_id = call.get('telephonySessionId')
                        if not session_id:
                            print("Call missing telephonySessionId, skipping...")
                            continue

                        # Check if already monitoring
                        with self.lock:
                            if session_id in self.monitored_sessions:
                                continue
                            self.monitored_sessions.add(session_id)
                        
                        # Get agent information - handle different data structures
                        agent_id = None
                        
                        # Try getting from 'extension' field (most common)
                        if 'extension' in call:
                            agent_extension = call['extension']
                            if isinstance(agent_extension, dict):
                                agent_id = agent_extension.get('id')
                            elif isinstance(agent_extension, (int, str)):
                                agent_id = agent_extension
                        
                        # Alternative: check 'from' field for extension info
                        if not agent_id and 'from' in call:
                            from_info = call['from']
                            if isinstance(from_info, dict) and 'extensionId' in from_info:
                                agent_id = from_info['extensionId']
                        
                        # Alternative: check parties in the call
                        if not agent_id and 'parties' in call:
                            for party in call['parties']:
                                if party.get('status', {}).get('code') == 'Answered':
                                    if 'extensionId' in party:
                                        agent_id = party['extensionId']
                                        break
                        
                        if agent_id:
                            print(f"\n{'='*50}")
                            print(f"NEW ACTIVE CALL DETECTED")
                            print(f"Session ID: {session_id}")
                            print(f"Agent Extension ID: {agent_id}")
                            
                            # Show additional call info if available
                            if 'from' in call:
                                from_info = call['from']
                                if isinstance(from_info, dict):
                                    print(f"From: {from_info.get('name', 'Unknown')} ({from_info.get('phoneNumber', 'N/A')})")
                            if 'to' in call:
                                to_info = call['to']
                                if isinstance(to_info, dict):
                                    print(f"To: {to_info.get('name', 'Unknown')} ({to_info.get('phoneNumber', 'N/A')})")
                            
                            print(f"{'='*50}\n")
                            
                            # Start supervision in a separate thread
                            threading.Thread(
                                target=self.initiate_supervision_and_listen, 
                                args=(session_id, agent_id),
                                daemon=True
                            ).start()
                        else:
                            print(f"Could not determine agent ID for session {session_id}")
                            print(f"Call data structure: {json.dumps(call, indent=2)}")
                            with self.lock:
                                self.monitored_sessions.discard(session_id)
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] No active calls found")

                time.sleep(10)  # Poll every 10 seconds
                
            except KeyboardInterrupt:
                print("\n\nShutdown signal received. Stopping monitoring service...")
                break
            except Exception as e:
                print(f"Unexpected error in monitoring loop: {e}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    print(f"Too many consecutive errors. Stopping monitor.")
                    break
                time.sleep(30)

    def initiate_supervision_and_listen(self, session_id, agent_id):
        """Helper to manage supervision and start the WebSocket listener."""
        try:
            supervision_data = self.supervise_call(session_id, agent_extension_id=agent_id)
            
            if supervision_data and 'media' in supervision_data:
                ws_uri = supervision_data['media'].get('uri')
                access_token = supervision_data['media'].get('accessToken')
                
                if ws_uri and access_token:
                    print(f"[{session_id}] Starting audio stream listener...")
                    self.start_audio_stream_listener(ws_uri, access_token, session_id)
                else:
                    print(f"[{session_id}] Missing WebSocket URI or access token in supervision response")
                    with self.lock: 
                        self.monitored_sessions.discard(session_id)
            else:
                print(f"[{session_id}] Failed to get supervision data. Check:")
                print(f"  - The call is still active")
                print(f"  - You have supervision permissions for this extension")
                print(f"  - The agent extension ID is correct")
                with self.lock: 
                    self.monitored_sessions.discard(session_id)
                    
        except Exception as e:
            print(f"[{session_id}] Error in supervision thread: {e}")
            with self.lock: 
                self.monitored_sessions.discard(session_id)

if __name__ == "__main__":
    # Get credentials from environment variables
    CLIENT_ID = os.getenv("RINGCENTRAL_CLIENT_ID")
    CLIENT_SECRET = os.getenv("RINGCENTRAL_CLIENT_SECRET")
    JWT_TOKEN = os.getenv("RINGCENTRAL_JWT_TOKEN")
    SERVER_URL = os.environ.get("RINGCENTRAL_SERVER_URL", "https://platform.ringcentral.com")
    
    if not all([CLIENT_ID, CLIENT_SECRET, JWT_TOKEN]):
        print("="*60)
        print("ERROR: Missing required environment variables")
        print("="*60)
        print("Please set the following environment variables:")
        print("  - RINGCENTRAL_CLIENT_ID")
        print("  - RINGCENTRAL_CLIENT_SECRET")
        print("  - RINGCENTRAL_JWT_TOKEN")
        print("\nOptional:")
        print("  - RINGCENTRAL_SERVER_URL (defaults to production)")
        print("="*60)
    else:
        print("="*60)
        print("RINGCENTRAL CALL MONITOR")
        print("="*60)
        
        # Create monitor instance
        monitor = RingCentralCallMonitor(CLIENT_ID, CLIENT_SECRET, JWT_TOKEN, SERVER_URL)
        
        # Authenticate
        if monitor.authenticate():
            # Select supervisor device
            if monitor.select_supervisor_device():
                # Start monitoring
                monitor.start_monitoring_loop()
            else:
                print("Failed to select supervisor device. Exiting.")
        else:
            print("Authentication failed. Please check your credentials.")