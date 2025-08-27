import json
import logging
import os
import tempfile
import requests
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
import groq
from app.ringcentral.authtoken import get_ringcentral_access_token

from app.core.config import settings
from app.modules.transcription.service import (
    analyze_sentiment,
    rate_call,
    extract_keywords,
    get_client_details,
    make_transcription_readable,
_call_groq_api
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Groq client
try:
    if not settings.GROQ_API_KEY:
        logger.error("GROQ_API_KEY is not set in environment; Groq client will not be initialized.")
    groq_client = groq.Groq(api_key=settings.GROQ_API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize Groq client: {e}")
    groq_client = None

def get_kafka_producer():
    """Initializes and returns a Kafka producer."""
    try:
        producer = KafkaProducer(
            bootstrap_servers=settings.KAFKA_BROKERS.split(','),
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            client_id=settings.KAFKA_CLIENT_ID
        )
        return producer
    except KafkaError as e:
        logger.error(f"Error creating Kafka producer: {e}")
        return None

def get_kafka_consumer():
    """Initializes and returns a Kafka consumer."""
    try:
        consumer = KafkaConsumer(
            settings.KAFKA_TRANSCRIPTION_TOPIC,
            bootstrap_servers=settings.KAFKA_BROKERS.split(','),
            value_deserializer=lambda v: json.loads(v.decode('utf-8')),
            group_id=settings.KAFKA_GROUP_ID,
            client_id=settings.KAFKA_CLIENT_ID,
            auto_offset_reset='earliest'
        )
        return consumer
    except KafkaError as e:
        logger.error(f"Error creating Kafka consumer: {e}")
        return None

def download_audio(url: str) -> str | None:
    """
    Downloads audio from a URL, determines its file type from the Content-Type header,
    and saves it to a temporary file with the correct extension.
    """
    # A simple map of common audio MIME types to file extensions
    MIME_TYPE_MAP = {
        'audio/mpeg': '.mp3',
        'audio/mp3': '.mp3',
        'audio/wav': '.wav',
        'audio/x-wav': '.wav',
        'audio/mp4': '.m4a',
        'audio/ogg': '.ogg',
        'audio/flac': '.flac',
        'audio/webm': '.webm',
    }

    try:
        # For RingCentral, always retrieve a fresh access token
        # You may want to cache this if your token is long-lived
        client_id = settings.RINGCENTRAL_CLIENT_ID
        client_secret = settings.RINGCENTRAL_CLIENT_SECRET
        jwt = settings.RINGCENTRAL_JWT
        access_token = None
        if client_id and jwt:
            try:
                access_token = get_ringcentral_access_token(client_id,client_secret ,jwt)
            except Exception as e:
                logger.error(f"Failed to retrieve RingCentral access token: {e}")
        # Remove any ?access_token= from URL if present
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        base_url = url.split('?')[0]
        url = base_url
        headers = {}
        if access_token:
            headers['Authorization'] = f'Bearer {access_token}'
        with requests.get(url, stream=True, timeout=90, headers=headers) as response:
            response.raise_for_status()

            # Determine file extension from Content-Type header
            content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
            suffix = MIME_TYPE_MAP.get(content_type, '.mp3') # Default to .mp3 if unknown
            
            if suffix == '.mp3' and content_type not in MIME_TYPE_MAP:
                logger.warning(f"Unknown Content-Type '{content_type}'. Defaulting to .mp3. This may cause issues.")

            # Create a temporary file with the correct suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    tmp_file.write(chunk)
                logger.info(f"Audio downloaded successfully to {tmp_file.name}")
                return tmp_file.name
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download audio from {url}: {e}")
        return None

def transcribe_audio(groq_client: groq.Groq, file_path: str) -> str | None:
    """Transcribes audio using Groq's Whisper model."""
    if not groq_client:
        logger.error("Groq client not available for transcription.")
        return None
    try:
        with open(file_path, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(os.path.basename(file_path), file.read()),
                model="whisper-large-v3-turbo", # Or "whisper-large-v3-turbo" if available/preferred
                response_format="verbose_json"
                
            )
        logger.info("Audio transcribed successfully.")
        return transcription.text
    except Exception as e:
        logger.error(f"Error during audio transcription: {e}")
        return None
    finally:
        # Clean up the temporary file
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Removed temporary audio file: {file_path}")

def process_transcription_job(message: dict, producer: KafkaProducer):
    """
    Downloads, transcribes, analyzes audio from a Kafka job,
    and sends the results to another topic.
    """
    try:
        call_id = message.get("callId")
        recording_url = message.get("recordingUrl")
        meta = message.get("meta", {})

        if not all([call_id, recording_url]):
            logger.warning(f"Skipping message, missing 'callId' or 'recordingUrl': {message}")
            return

        # 1. Download audio
        audio_file_path = download_audio(recording_url)
        if not audio_file_path:
            return # Error already logged

        # 2. Transcribe audio
        call_transcript = transcribe_audio(groq_client,file_path=audio_file_path)
        #Make Transcription Readable in Question Answer format using Groq
        
        if not call_transcript:
            return # Error already logged

        # 3. Analyze Transcript
        sentiment, sentiment_score = analyze_sentiment(groq_client, call_transcript)
        rating, _ = rate_call(groq_client, call_transcript)
        keywords = extract_keywords(groq_client, call_transcript)

        # 3.5 Get client details if available
       
        client_details = get_client_details(groq_client, call_transcript)
        email = client_details.get("email", "")
        name= client_details.get("name", "")

        #3.7 Get Formatted Transcription
        formatted_transcript = make_transcription_readable(groq_client, call_transcript)
        # 4. Prepare response payload
        response_payload = {
            "sentiment": sentiment,
            "sentiment_score": sentiment_score,
            "keywords": keywords,
            "call_rating": rating,
            "client_email": email,
            "client_name": name,
            "call_transcript": call_transcript
        }

        # 5. Send to call-update-jobs topic
        producer.send(settings.KAFKA_CALL_UPDATE_TOPIC, value=response_payload)
        producer.flush()
        logger.info(f"Successfully processed and sent update for callId: {call_id}")

    except Exception as e:
        logger.error(f"Unhandled error processing message: {message}. Error: {e}")

def consume_messages():
    """Main consumer loop to listen for and process messages."""
    consumer = get_kafka_consumer()
    producer = get_kafka_producer()

    if not consumer or not producer:
        logger.error("Could not initialize Kafka client. Exiting consumer.")
        return

    logger.info(f"Listening for messages on topic: {settings.KAFKA_TRANSCRIPTION_TOPIC}")
    for message in consumer:
        logger.info(f"Received message for callId: {message.value.get('callId')}")
        process_transcription_job(message.value, producer)

if __name__ == "__main__":
    consume_messages()