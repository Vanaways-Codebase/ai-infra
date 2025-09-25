# Call Transcription Analysis API

A FastAPI backend for analyzing call transcriptions between users and agents.

## Features

- Sentiment Analysis (positive or negative)
- Call Rating (out of 10)
- Keywords Extraction and Frequency Analysis

## Project Structure

```
project_root/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry point
│   ├── core/                   # Core components
│   │   ├── __init__.py
│   │   ├── config.py           # Configuration settings
│   │   ├── dependencies.py     # Shared dependencies (DB connection, etc.)
│   │   └── middleware.py       # Global middleware
│   ├── api.py                  # API router aggregation
│   └── modules/                # Business logic modules
│       ├── __init__.py
│       ├── transcription/      # Transcription analysis module
│       │   ├── __init__.py
│       │   ├── models.py       # Database models
│       │   ├── schemas.py      # Pydantic schemas
│       │   ├── service.py      # Business logic
│       │   └── routes.py       # FastAPI routes/endpoints
│       └── user/               # User module
│           ├── __init__.py
│           ├── models.py
│           ├── schemas.py
│           ├── service.py
│           └── routes.py
├── functions/                  # Azure Functions (when needed)
├── tests/                      # Test suite
├── .env                        # Environment variables
├── requirements.txt            # Dependencies
└── README.md
```

## Setup

1. Clone the repository
2. Create a virtual environment: `python -m venv venv`
3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - Unix/MacOS: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Set up environment variables in `.env`
6. Run the application: `uvicorn app.main:app --reload`

## API Documentation

Once the application is running, you can access the API documentation at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`


VM
pm2 start bash -- -c "source /home/azureuser/ai-infra/vanaways/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000"

## Azure Service Bus Integration

The FastAPI app now starts an Azure Service Bus listener during startup when the following environment variables are set:

- `AZURE_SERVICEBUS_CONNECTION_STRING`
- `AZURE_SERVICEBUS_QUEUE_NAME`
- (`AZURE_SERVICEBUS_MAX_MESSAGE_COUNT` and `AZURE_SERVICEBUS_MAX_WAIT_SECONDS` are optional tuning knobs.)

Incoming messages are decoded into `AudioProcessingMessage` objects and processed with the same transcription pipeline used by the REST endpoint. See `app/modules/servicebus/worker.py` for the entry point and `app/modules/transcription/job_processor.py` for the shared processing logic.

## Node.js Sender Example

A minimal TypeScript client that publishes `AudioProcessingMessage` payloads lives under `examples/servicebus-sender/`.

```bash
cd examples/servicebus-sender
npm install
echo "AZURE_SERVICEBUS_CONNECTION_STRING=<connection-string>" >> .env
echo "AZURE_SERVICEBUS_QUEUE_NAME=<queue-name>" >> .env
npm start                      # builds and sends a sample payload
npm start ./payload.json       # optional: send a custom JSON file
npm run send -- ./payload.json # quicker path using ts-node directly
```

To send a custom payload:

```bash
npm start ./path/to/message.json
```

The JSON file should resemble the webhook payload:

```json
{
  "callId": "abc123",
  "audioUrl": "https://example.com/call.mp3",
  "timestamp": "2024-01-01T00:00:00Z",
  "ringcentralData": { "any": "metadata" },
  "priority": "high"
}
```

Tip: set `DRY_RUN=1` in the environment to print the payload without calling Azure (handy when testing locally without credentials).

### Standalone Python Listener

To exercise the FastAPI listener logic without running the entire web app, use the helper entry point:

```bash
export AZURE_SERVICEBUS_CONNECTION_STRING="<connection-string>"
export AZURE_SERVICEBUS_QUEUE_NAME="<queue-name>"
export GROQ_API_KEY="<groq-key>"
pip install -r requirements.txt
python -m app.modules.servicebus.dev_listener
```

Press `Ctrl+C` to stop the loop. The script shares the same handler that the FastAPI application uses, so behaviour matches production.
