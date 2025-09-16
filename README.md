# AI Infra: Call Monitoring & Transcription

This project provides tools for monitoring agent calls and transcribing audio using OpenAI's API. It includes:
- **call_transcriber_app.py**: A GUI application for monitoring agent calls and live transcription.
- **call_monitoring.py**: A command-line tool for monitoring RingCentral calls and streaming audio.
- **Tr2asncr.py**: A dual audio transcriber for system and microphone audio.

## Requirements
Install dependencies with:
```
pip install -r requirements.txt
```

## Setup
1. Create a `.env` file in the project directory with the following variables:
```
RINGCENTRAL_CLIENT_ID=your_client_id
RINGCENTRAL_CLIENT_SECRET=your_client_secret
RINGCENTRAL_JWT_TOKEN=your_jwt_token
RINGCENTRAL_SERVER_URL=https://platform.ringcentral.com
OPENAI_API_KEY=your_openai_api_key
```
2. Install dependencies as above.

## How to Run
### 1. GUI Call Monitor & Transcriber
```
python call_transcriber_app.py
```
- Enter the agent extension in the GUI and click "Start Monitoring".
- The app will display live status and transcriptions.

### 2. Command-Line Call Monitoring
```
python call_monitoring.py
```
- Monitors RingCentral calls and streams audio for supervision.

### 3. Dual Audio Transcriber
```
python Tr2asncr.py
```
- Transcribes both system and microphone audio using OpenAI.

## How It Works
- **call_transcriber_app.py**: Uses RingCentral API to monitor agent calls, records audio, and transcribes using OpenAI. The GUI displays live status and transcriptions.
- **call_monitoring.py**: Authenticates with RingCentral, monitors active calls, and streams audio for supervision.
- **Tr2asncr.py**: Records system and microphone audio, sends to OpenAI for transcription, and prints results.

## Notes
- Ensure your API keys and credentials are set in `.env`.
- For GUI, make sure your system supports `tkinter`.
- For audio, ensure your system supports `soundcard` and has the necessary drivers.