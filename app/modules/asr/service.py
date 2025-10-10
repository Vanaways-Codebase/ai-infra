import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import settings
from app.core.database.mongodb import db
from app.core.openai_client import (
    get_azure_openai_whisper_client,
    get_azure_openai_client,
    get_openai_client,
)
from app.ringcentral.service import download_audio, get_recording_audio_url
from app.services.azure.openai.whisper_rateLimiter import whisper_rate_limiter
from app.services.openai.local_whisper import local_whisper



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
    

    """Transcribe using local Whisper model."""
    try:
        result = await local_whisper.transcribe(
            audio_path=file_path,
            language="en",
            task="transcribe"
        )
        return result
    except Exception as e:
        logger.error(f"Local Whisper transcription failed: {e}")
        raise
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
    Transcribe an audio file using local Whisper or Azure Whisper.
    Automatically selects based on USE_LOCAL_WHISPER setting.
    """
    
    # Choose transcription method based on configuration
    if settings.USE_LOCAL_WHISPER:
        logger.info("Using LOCAL Whisper (no rate limits!)")
        transcript_data = await _transcribe_with_local_whisper(file_path)
    else:
        logger.info("Using AZURE Whisper (with rate limiting)")
        # Acquire rate limit permission before making the API call
        await whisper_rate_limiter.acquire()
        transcript_data = await _transcribe_with_azure_whisper(file_path)
    
    # Extract text and segments
    text = transcript_data.get("text", "")
    segments = transcript_data.get("segments", [])
    duration = transcript_data.get("duration", 0)
    
    # Create structured transcript from segments
    structured_transcript = await _generate_structured_transcript(text, segments)
    
    # Analyze the transcript
    analysis = await _analyze_transcript(text, structured_transcript)
    
    # Generate transcript ID
    transcript_id = f"transcription_{datetime.now().strftime('%Y%m%d%H%M%S')}_{hash(text) % 10000}"
    
    # Prepare vehicle tags
    vehicle_tags_dict = _format_vehicle_tags(text, analysis.get("tags", []))
    
    # Extract contact info
    contacts_dict = analysis.get("contacts") or {}
    from .schemas import ContactExtraction
    
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
        confidence=None,
        id=transcript_id,
        call_summary=analysis.get("summary", "Analysis unavailable"),
        call_analysis=analysis.get("analysis", "Unable to analyze"),
        buyer_intent=analysis.get("buyer_intent_reason", "Unknown"),
        buyer_intent_score=analysis.get("buyer_intent_score", 0.0),
        buyer_intent_reason=analysis.get("buyer_intent_reason", "Unknown"),
        agent_recommendation=analysis.get("agent_recommendation", "Review manually"),
        structured_transcript=structured_transcript,
        keywords=analysis.get("keywords", []) or [],
        mql_assessment=analysis.get("mql_score", 0.0),
        sentiment_analysis=analysis.get("sentiment", 0.0),
        customer_rating=analysis.get("rating", 0.0),
        call_type=analysis.get("call_type", "unknown"),
        summary=analysis.get("summary", "Analysis unavailable"),
        vehicle_tags=vehicle_tags_dict,
        contact_extraction=contact_extraction,
        audio_duration=duration
    )

def get_color_for_tag(tag: str) -> str:
    """Derive a deterministic, repeatable color for a given tag."""
    colors = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
        "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
        "#bcbd22", "#17becf"
    ]
    digest = hashlib.sha256(tag.lower().encode("utf-8")).digest()
    return colors[digest[0] % len(colors)]


def _format_vehicle_tags(transcript_text: str, raw_tags: Optional[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Normalize raw tag output into structured metadata with counts and colors."""
    if not raw_tags:
        return []

    safe_transcript = (transcript_text or "").lower()
    tag_order: List[str] = []
    fallback_counts: Dict[str, int] = {}

    for entry in raw_tags:
        if isinstance(entry, dict):
            for raw_tag, raw_count in entry.items():
                tag = str(raw_tag).strip()
                if not tag:
                    continue
                lowered = tag.lower()
                tag_order.append(tag)
                try:
                    count_candidate = int(raw_count)
                    if count_candidate > 0:
                        fallback_counts[lowered] = max(fallback_counts.get(lowered, 0), count_candidate)
                except (TypeError, ValueError):
                    continue
        elif isinstance(entry, str):
            tag = entry.strip()
            if tag:
                tag_order.append(tag)

    if not tag_order:
        return []

    # Preserve first occurrence order while deduplicating (case-insensitive)
    seen: set[str] = set()
    unique_tags: List[str] = []
    for tag in tag_order:
        lowered = tag.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_tags.append(tag)

    formatted_tags: List[Dict[str, Any]] = []
    for tag in unique_tags:
        lowered = tag.lower()
        # Count literal occurrences in transcript text
        pattern = r"(?<!\w){}(?!\w)".format(re.escape(lowered))
        count = len(re.findall(pattern, safe_transcript))
        if count == 0:
            count = fallback_counts.get(lowered, 0)
        if count == 0:
            continue
        formatted_tags.append(
            {
                "tag": tag,
                "count": count,
                "color": get_color_for_tag(tag),
            }
        )

    # Sort by highest count first for ergonomics
    formatted_tags.sort(key=lambda item: item["count"], reverse=True)
    return formatted_tags


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
                "description": "Vehicle-related terms (makes, models, types) as clean strings without frequency counts, Eg: {'ford': '8'},'{transit custom': '8'}}"
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
        client = get_azure_openai_client()

        # Build prompt with structured format
        conversation = "\n".join([
            f"{turn['speaker'].upper()}: {turn['message']}"
            for turn in structured_transcript
        ])

        # Compose a comprehensive prompt for the LLM, integrating granular sub-prompts for each analysis field.
        prompt = f"""
    Analyze this Vanaways sales call transcript and extract the required information.

    Transcript:
    {conversation}

    For each of the following, analyze the transcript and provide the result in the specified format:

    - keywords: Extract the most important keywords and phrases from this van-related conversation. Focus on vehicle types, models, makes, leasing/sales terms, business needs, and action items. Return only a JSON array of strings, e.g. ["keyword1", "keyword2", "keyword3"].
    - mql_assessment: Score this van-related conversation as a Marketing Qualified Lead (MQL) from 0 to 10. Consider: interest level, budget signals, authority to decide, urgency, and product fit. Return only the number.
    - sentiment_analysis: Rate the overall sentiment of this van-related customer conversation from 0 (very negative) to 10 (very positive). Consider satisfaction, tone, agent helpfulness, issue resolution, and engagement. Return only the number.
    - customer_rating: Based on this van-related conversation, rate how satisfied the customer seems. Scale: 0 = very unhappy, 5-6 = neutral, 9-10 = very happy. Return only the number.
    - call_type: Classify this van-related conversation into one of: "High Score", "Hot Lead", "Customer Issue", "General Inquiry", "Follow Up", "Other". Return only the category name.
    - summary: Provide a concise one-line summary of this van-related conversation (max 100 characters). Example: "Customer needs leasing for 5 Ford Transit vans, asks for pricing this month".
    - vehicle_tags: Extract all vehicle-related terms from this conversation (makes, models, types). Count frequency of each term. Return only valid JSON. Example: {{"ford": "2", "transit": "3", "van": "5"}}. If none, return {{}}.
    - contact_extraction: From this van-related conversation, extract ONLY the CUSTOMER's name (first name is fine if full name not given) and email address if present. Ignore any names that are followed by 'from Vanaways' or similar, since those are Agents. Correct any 'Banaways' typos to 'Vanaways'. Return ONLY JSON in this exact format: {{"name":"<name or empty>","email":"<email or empty>"}}.
    - Purchase intent signals and next steps: Make sure buyer_intent_score is only calculated from clear purchase intent signals (If call is being to sales call then analyze for intent, otherwise return 0), same for buyer_intent_reason if not then empty string.
    - agent_recommendation: Based on this van-related conversation, suggest the best next action for the sales agent.
    - Provide a detailed analysis of the call, including strengths and weaknesses of the sales approach.

    NOTE: If the transcript is empty or lacks meaningful content, respond with null, empty lists, or 0 for all fields as appropriate.

    Provide a complete analysis with insights that would help Vanaways improve their sales process.
    """

        # Generate analysis using GPT with structured output
        completion = await asyncio.to_thread(
            lambda: client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                "role": "system",
                "content": (
                    "You are an assistant that analyzes van-related customer conversations of Vanaways."
                    "Provide concise, accurate, and structured insights based on the transcript."
                    "Analyze properly and do not make up information."
                )
                },
                {"role": "user", "content": prompt}
            ],
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
        return {}

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

async def _transcribe_with_local_whisper(file_path: Path) -> Dict[str, Any]:
    """Transcribe using local Whisper model."""
    try:
        result = await local_whisper.transcribe(
            audio_path=file_path,
            language="en",
            task="transcribe"
        )
        return result
    except Exception as e:
        logger.error(f"Local Whisper transcription failed: {e}")
        raise


async def _transcribe_with_azure_whisper(file_path: Path) -> Dict[str, Any]:
    """Transcribe using Azure OpenAI Whisper API."""
    client = get_azure_openai_whisper_client()
    model = "whisper"
    
    def _transcribe():
        with open(file_path, "rb") as file_stream:
            return client.audio.transcriptions.create(
                model=model,
                file=file_stream,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
                prompt=(
                    "This is a sales call recording between a customer and a sales agent from Vanaways. "
                    "Please accurately identify and separate the speakers throughout the conversation."
                )
            )
    
    transcript = await asyncio.to_thread(_transcribe)
    
    # Convert Azure response to standard format
    return {
        "text": getattr(transcript, "text", ""),
        "segments": _extract_segments(transcript),
        "duration": getattr(transcript, "duration", 0)
    }
async def calculate_enhanced_status(call: dict) -> str:
    """
    Asynchronously calculate the enhanced status of a call based on its properties.

    Args:
        call: Dictionary containing call details.

    Returns:
        A string representing the enhanced status.
    """
    call_status = call.get("call_status")
    missed_call = call.get("missed_call")
    direction = call.get("direction")
    summary = call.get("summary", "")
    transcription_status = call.get("transcriptionStatus")
    recording_url = call.get("recordingUrl")
    to_number = call.get("toNumber", "")

    if call_status == "Completed":
        if missed_call and direction == "Outbound":
            return "not answered"
        elif missed_call and direction == "Inbound":
            return "missed call"
        elif summary and summary.strip():
            return "completed"
        elif transcription_status in ["pending", "processing"]:
            return "transcribing"
        elif transcription_status == "completed" and (not summary or not summary.strip() or not recording_url):
            return "dropped call"
        else:
            return "transcribing"
    elif call_status == "In Progress" and to_number and to_number.strip() != "":
        return "in progress"
    else:
        return "in progress"
