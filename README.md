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
