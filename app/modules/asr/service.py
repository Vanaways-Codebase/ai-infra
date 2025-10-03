import asyncio
import json
import logging
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.database.mongodb import db
from app.core.openai_client import (
    get_azure_openai_client,
    get_azure_openai_eastus_client,
    get_openai_client,
)
from app.ringcentral.service import download_audio, get_recording_audio_url

from .schemas import TranscriptionResult

logger = logging.getLogger(__name__)

async def manual_transcribe(limit: int = 1) -> List[Dict[str, Any]]:
    """Manually transcribe the most recent calls in MongoDB."""

    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    disconnect_after = False
    try:
        if db.database is None:
            await db.connect()
            disconnect_after = True
        calls_collection = db.get_collection("calls")
    except Exception as exc:
        logger.error("Unable to access MongoDB: %s", exc)
        raise

    cursor = (
        calls_collection
        .find({"ringCentralId": {"$exists": True, "$ne": None}})
        .sort([("createdAt", -1), ("_id", -1)])
        .limit(limit)
    )

    calls = await cursor.to_list(length=limit)

    print(f"\nFound {len(calls)} calls to process")

    processed: List[Dict[str, Any]] = []

    for call_data in calls:
        call_id = call_data.get("_id")
        ring_central_id = (
            call_data.get("ringCentralId")
            or call_data.get("ring_central_id")
            or call_data.get("recordingId")
        )

        if not ring_central_id:
            logger.warning("Skipping call %s without ringCentralId", call_id)
            continue

        try:
            audio_url = await get_recording_audio_url(str(ring_central_id))
            transcription = await transcribe(url=audio_url)
            transcription_payload = transcription.model_dump()

            update_doc: Dict[str, Any] = {
                "callAnalysis": transcription.call_analysis,
                "transcriptionResult": transcription_payload,
                "transcriptionUpdatedAt": datetime.now(timezone.utc),
            }

            await calls_collection.update_one(
                {"_id": call_id},
                {"$set": update_doc}
            )

            processed.append(
                {
                    "call_id": str(call_id) if call_id is not None else None,
                    "ring_central_id": ring_central_id,
                    "status": transcription.status,
                }
            )
        except Exception as exc:
            logger.exception(
                "Manual transcription failed for ringCentralId=%s", ring_central_id
            )

    if disconnect_after:
        await db.disconnect()

    return processed
    

async def transcribe(recording_id: Optional[str] = None, url: Optional[str] = None) -> TranscriptionResult:
    """
    Transcribe audio using OpenAI's Whisper model.

    Args:
        recording_id: Optional RingCentral recording ID
        url: Optional direct URL to audio file

    Returns:
        TranscriptionResult containing the transcription and related metadata

    Raises:
        ValueError: If neither recording_id nor url is provided
    """
    if not recording_id and not url:
        raise ValueError("Either recording_id or url must be provided")

    # Create a temporary file path for the download
    temp_dir = Path(os.environ.get("TEMP_DIR", "/tmp"))
    temp_dir.mkdir(exist_ok=True)
    temp_file = temp_dir / \
        f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"

    try:
        # Download the audio file
        downloaded_file = await download_audio(
            output_path=str(temp_file),
            recording_id=recording_id,
            url=url
        )

        # Transcribe the audio file
        result = await _transcribe_file(downloaded_file)
        return result

    finally:
        # Clean up the temporary file
        if temp_file.exists():
            try:
                os.remove(temp_file)
            except OSError as e:
                logger.warning(
                    f"Failed to remove temporary file {temp_file}: {e}")


async def _transcribe_file(file_path: Path) -> TranscriptionResult:
    """
    Transcribe an audio file using OpenAI's Whisper model.

    Args:
        file_path: Path to the audio file

    Returns:
        TranscriptionResult object
    """
    client = get_openai_client()
    model = (settings.OPENAI_TRANSCRIPTION_MODEL or "").strip() or "whisper-1"

    # Use asyncio.to_thread for non-async operations
    def _transcribe():
        with open(file_path, "rb") as file_stream:
            return client.audio.transcriptions.create(
                model=model,
                file=file_stream,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
                prompt="This is a sales call recording between a customer and a sales agent of Vanaways. Please identify and separate the speakers accurately. The conversation involves a customer inquiry and agent responses about products or services. Ensure proper speaker diarization to distinguish between customer and agent throughout the call. Also identify and mark any voicemail messages and hold ringtones/music that may occur during the call."
            )

    transcript = await asyncio.to_thread(_transcribe)

    # print("\n\nTRANSCRIPT", transcript)  # Debug output of the full transcript

    # Extract text and segments from transcript
    text = getattr(transcript, "text", "") or ""
    segments = _extract_segments(transcript)

    # Create structured transcript from segments
    structured_transcript = await _generate_structured_transcript(text, segments)

    # Now analyze the transcript for additional information
    analysis = await _analyze_transcript(text, structured_transcript)

    # Get transcription ID
    transcript_id = getattr(transcript, "id", None)
    if not transcript_id:
        transcript_id = f"transcription_{datetime.now().strftime('%Y%m%d%H%M%S')}_{hash(text) % 10000}"

    # Prepare vehicle tags from regular tags - convert list to dict format expected by schema
    vehicle_tags_dict = {}
    for i, tag in enumerate(analysis.get("tags", [])):
        if tag and isinstance(tag, str):
            vehicle_tags_dict[f"tag_{i+1}"] = tag
            
    # Get contact info from analysis and create a ContactExtraction object
    contacts_dict = analysis.get("contacts", {})
    from .schemas import ContactExtraction
    
    # Create ContactExtraction object from dictionary
    contact_extraction = ContactExtraction(
        name=contacts_dict.get("name"),
        email=contacts_dict.get("email"),
        phone=contacts_dict.get("phone"),
        company=contacts_dict.get("company"),
        address=contacts_dict.get("address"),
        city=contacts_dict.get("city")
    )

    return TranscriptionResult(
        status="completed",
        text=text,
        confidence=None,  # Whisper does not provide overall confidence
        id=transcript_id,
        call_summary=analysis.get("summary"),
        call_analysis=analysis.get("analysis"),
        buyer_intent=analysis.get("buyer_intent_reason"),
        buyer_intent_score=analysis.get("buyer_intent_score"),
        buyer_intent_reason=analysis.get("buyer_intent_reason"),
        agent_recommendation=analysis.get("agent_recommendation"),
        structured_transcript=structured_transcript,
        keywords=analysis.get("keywords", []),
        mql_assessment=analysis.get("mql_score", 0.0),
        sentiment_analysis=analysis.get("sentiment", 0.0),
        customer_rating=analysis.get("rating", 0.0),
        call_type=analysis.get("call_type", ""),
        summary=analysis.get("summary", ""),
        vehicle_tags=vehicle_tags_dict,
        contact_extraction=contact_extraction,  # Use the ContactExtraction model
    )


async def _analyze_transcript(text: str, structured_transcript: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze transcript to extract keywords, generate summaries, and other insights.

    Args:
        text: Full transcript text
        structured_transcript: Structured transcript with speaker turns

    Returns:
        Dictionary with analysis results
    """
    if not text.strip():
        return {}

    # Initialize with default values
    call_analysis_schema = {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "minItems": 0
                    },
                    "summary": {
                        "type": ["string", "null"]
                    },
                    "tags": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "minItems": 0
                    },
                    "sentiment": {
                        "type": ["number", "null"]
                    },
                    "mql_score": {
                        "type": ["number", "null"]
                    },
                    "rating": {
                        "type": ["number", "null"]
                    },
                    "call_type": {
                        "type": ["string", "null"]
                    },
                    "buyer_intent_score": {
                        "type": ["number", "null"]
                    },
                    "buyer_intent_reason": {
                        "type": ["string", "null"]
                    },
                    "agent_recommendation": {
                        "type": ["string", "null"]
                    },
                    "analysis": {
                        "type": ["string", "null"]
                    },
                    "contacts": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": ["string", "null"]
                            },
                            "email": {
                                "type": ["string", "null"],
                                "format": "email"
                            },
                            "phone": {
                                "type": ["string", "null"]
                            },
                            "company": {
                                "type": ["string", "null"]
                            },
                            "address": {
                                "type": ["string", "null"]
                            },
                            "city": {
                                "type": ["string", "null"]
                            }
                        },
                        "required": ["name", "email", "phone", "company", "address", "city"],
                        "additionalProperties": False
                    }
                },
                "required": ["keywords", "summary", "tags", "sentiment", "mql_score", "rating", "call_type", "buyer_intent_score", "buyer_intent_reason", "agent_recommendation", "analysis", "contacts"],
                "additionalProperties": False
            }

    # Use OpenAI to analyze the transcript
    try:
        client = get_openai_client()

        # Build prompt with structured format
        conversation = "\n".join([
            f"{turn['speaker'].upper()}: {turn['message']}"
            for turn in structured_transcript
        ])

        prompt = f"""Analyze this Vanaways sales call transcript and extract the required information.

        Transcript:
        {conversation}

        Focus on identifying:
        - keywords: Extract the most important keywords and phrases from this van-related conversation. Focus on vehicle types, models, makes, leasing/sales terms, business needs, and action items.
        - mql_assessment: Score this van-related conversation as a Marketing Qualified Lead (MQL) from 0 to 10. Consider: interest level, budget signals, authority to decide, urgency, and product fit. Return only the number.
        - sentiment_analysis: Rate the overall sentiment of this van-related customer conversation from 0 (very negative) to 10 (very positive). Consider satisfaction, tone, agent helpfulness, issue resolution, and engagement. Return only the number.
        - customer_rating: Based on this van-related conversation, rate how satisfied the customer seems. Scale: 0 = very unhappy, 5-6 = neutral, 9-10 = very happy. Return only the number.
        - call_type: Classify this van-related conversation into one of: \"High Score\", \"Hot Lead\", \"Customer Issue\", \"General Inquiry\", \"Follow Up\", \"Other\". Return only the category name.
        - summary: Provide a concise summary of this van-related conversation.
        - vehicle_tags as Tags: Extract all vehicle-related terms from this conversation (makes, models, types). Count frequency of each term.
        - Purchase intent signals and next steps
        - Any customer contact details shared
        
        Provide a complete analysis with insights that would help Vanaways improve their sales process."""

        # Generate analysis using GPT with structured output
        completion = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role": "user", "content": prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "call_analysis",
                        "schema": call_analysis_schema,
                        "strict": True
                    }
                }
            )
        )

        # Parse response
        content = completion.choices[0].message.content
        result = json.loads(content)

        # Debug output of the parsed result
        print("\n\nANALYSIS RESULT", result)

        return result
    except Exception as e:
        logger.error(f"Error analyzing transcript: {str(e)}")

def _extract_segments(transcript: Any) -> List[Dict[str, Any]]:
    """Extract segments from the transcript object."""
    raw_segments = getattr(transcript, "segments", None)
    segments: List[Dict[str, Any]] = []

    if isinstance(raw_segments, list):
        for seg in raw_segments:
            if isinstance(seg, dict):
                start = seg.get("start")
                end = seg.get("end")
                text = seg.get("text")
            else:
                start = getattr(seg, "start", None)
                end = getattr(seg, "end", None)
                text = getattr(seg, "text", None)

            if text is None:
                continue

            segment_entry: Dict[str, Any] = {"text": str(text)}
            if isinstance(start, (int, float)):
                segment_entry["start"] = float(start)
            if isinstance(end, (int, float)):
                segment_entry["end"] = float(end)
            segments.append(segment_entry)

    return segments


async def _generate_structured_transcript(text: str, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Generate a structured transcript from text and segments.

    Args:
        text: The raw transcript text
        segments: List of segment dictionaries with text, start, and end

    Returns:
        List of structured transcript entries
    """
    if not text.strip():
        return []

    structured: List[Dict[str, Any]] = []

    # Create structured transcript from segments
    current_speaker = "agent"  # Start with agent as default

    for idx, segment in enumerate(segments):
        # More sophisticated speaker detection using text content
        text_content = segment.get("text", "").strip().lower()

        # Check for speaker indicators in text
        is_agent = any(x in text_content for x in [
                       "hi, this is", "speaking", "how can i help", "vanaways", "i'm from"])
        is_customer = any(x in text_content for x in [
                          "i'm looking", "i want", "i need", "call about", "interested in"])

        # Only change speaker if there's a strong indicator
        if is_agent:
            current_speaker = "agent"
        elif is_customer:
            current_speaker = "customer"
        elif idx > 0 and len(structured) > 0:
            # Alternate speakers for normal conversation flow if no clear indicators
            prev_speaker = structured[-1]["speaker"]
            current_speaker = "customer" if prev_speaker == "agent" else "agent"

        # Format timestamp as string dictionary for compatibility with TranscriptUtterance schema
        start_time = segment.get("start")
        end_time = segment.get("end")
        timestamp = {
            "start": str(start_time) if start_time is not None else "0",
            "end": str(end_time) if end_time is not None else ""
        }

        structured.append({
            "speaker": current_speaker,
            "message": segment.get("text", ""),
            "timestamp": timestamp,
        })

    # If no segments, create from full text
    if not structured and text.strip():
        structured.append({
            "speaker": "agent",  # Default speaker for single-entry transcript
            "message": text.strip(),
            "timestamp": {"start": "0", "end": ""},
        })

    return structured
