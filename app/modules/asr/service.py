import json
import logging
import mimetypes
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from app.core.config import settings
from app.core.openai_client import get_openai_client


logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    status: str
    text: str
    confidence: Optional[float] = None
    id: Optional[str] = None
    call_summary: Optional[str] = None
    call_analysis: Optional[str] = None
    buyer_intent: Optional[str] = None
    agent_recommendation: Optional[str] = None
    structured_transcript: Optional[List[Dict[str, Any]]] = None
    keywords: Optional[List[str]] = None
    mql_assessment: Optional[float] = None
    sentiment_analysis: Optional[float] = None
    customer_rating: Optional[float] = None
    call_type: Optional[str] = None
    summary: Optional[str] = None
    vehicle_tags: Optional[Dict[str, str]] = None
    contact_extraction: Optional[Dict[str, str]] = None


def _determine_suffix(content_type: Optional[str], fallback: str = ".mp3") -> str:
    if content_type:
        suffix = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if suffix:
            return suffix
    return fallback


def _download_audio_to_tempfile(audio_url: str) -> str:
    response = requests.get(audio_url, stream=True, timeout=60)
    response.raise_for_status()
    suffix = _determine_suffix(response.headers.get("content-type"))
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                tmp_file.write(chunk)
        return tmp_file.name


def _transcribe_from_path(path: str) -> TranscriptionResult:
    client = get_openai_client()
    model = (settings.OPENAI_TRANSCRIPTION_MODEL or "").strip() or "whisper-1"
    with open(path, "rb") as file_stream:
        transcript = client.audio.transcriptions.create(
            model=model,
            file=file_stream,
        )
    text = getattr(transcript, "text", "") or ""
    segments = _extract_segments(transcript)
    insights = _generate_call_insights(text)
    structured_transcript = _generate_structured_transcript(text, segments)
    analysis_suite = _generate_analysis_outputs(text)
    summary = _stringify_insight(insights.get("summary"))
    analysis = _stringify_insight(insights.get("analysis"))
    buyer_intent = _stringify_insight(insights.get("buyer_intent"))
    agent_reco = _stringify_insight(insights.get("agent_recommendation"))
    return TranscriptionResult(
        status="completed",
        text=text,
        confidence=None,
        id=getattr(transcript, "id", None),
        call_summary=summary,
        call_analysis=analysis,
        buyer_intent=buyer_intent,
        agent_recommendation=agent_reco,
        structured_transcript=structured_transcript,
        keywords=analysis_suite.get("keywords"),
        mql_assessment=analysis_suite.get("mql_assessment"),
        sentiment_analysis=analysis_suite.get("sentiment_analysis"),
        customer_rating=analysis_suite.get("customer_rating"),
        call_type=analysis_suite.get("call_type"),
        summary=analysis_suite.get("summary"),
        vehicle_tags=analysis_suite.get("vehicle_tags"),
        contact_extraction=analysis_suite.get("contact_extraction"),
    )


def _generate_call_insights(transcript_text: str) -> dict:
    if not transcript_text.strip():
        return {"summary": "", "analysis": "", "buyer_intent": "", "agent_recommendation": ""}

    model = (settings.OPENAI_INSIGHTS_MODEL or "").strip() or "gpt-4o-mini"
    # Keep prompt concise to control latency and cost while ensuring structured output
    prompt = (
        "You are an expert call analyst. Given the call transcript, provide a concise JSON object with the "
        "keys: summary, analysis, buyer_intent, agent_recommendation. Summary must be 3-5 bullet sentences "
        "covering the call flow. Analysis should capture tone, objections, and pivotal moments. Buyer intent "
        "should classify likelihood to purchase and cite supporting evidence. Agent recommendation must list "
        "the top next actions for the agent. Keep responses under 120 words per field and avoid markdown."
    )

    raw_text = _call_openai_json(
        model=model,
        system_prompt=prompt,
        user_content=transcript_text[:8000],
        enforce_json_object=True,
    )

    if not raw_text:
        return {"summary": "", "analysis": "", "buyer_intent": "", "agent_recommendation": ""}

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {
            "summary": raw_text,
            "analysis": "",
            "buyer_intent": "",
            "agent_recommendation": "",
        }


def _generate_structured_transcript(transcript_text: str, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not transcript_text.strip():
        return []

    model = (settings.OPENAI_INSIGHTS_MODEL or "").strip() or "gpt-4o-mini"
    # Limit payload size to avoid excessive context for long calls
    trimmed_segments = segments[:120] if segments else []
    payload = {
        "segments": trimmed_segments,
        "transcript": transcript_text[:12000],
        "instructions": "Label each utterance as agent or customer and preserve chronological order.",
    }
    system_prompt = (
        "You transform call transcripts into structured JSON. Return a JSON array where each element has the "
        "keys speaker, message, start, end. Speaker must be either agent or customer. If unsure, infer from "
        "context but keep the best guess. Start and end should be the segment start/end in seconds if provided; "
        "otherwise estimate monotonically increasing floats. Message should contain the cleaned utterance text."
    )

    raw_text = _call_openai_json(
        model=model,
        system_prompt=system_prompt,
        user_content=json.dumps(payload, ensure_ascii=False),
        enforce_json_object=False,
    )

    if not raw_text:
        return []

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, dict):
        if "utterances" in parsed and isinstance(parsed["utterances"], list):
            parsed = parsed["utterances"]
        else:
            parsed = list(parsed.values())

    if not isinstance(parsed, list):
        return []

    base_time = datetime.now(timezone.utc)
    structured: List[Dict[str, Any]] = []
    for idx, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker", "unknown")).strip().lower()
        if speaker not in {"agent", "customer"}:
            speaker = "agent" if idx % 2 == 0 else "customer"
        message = _stringify_insight(item.get("message")).strip()
        if not message:
            continue
        start_val = item.get("start")
        timestamp_iso = None
        if isinstance(start_val, (int, float)):
            timestamp_iso = _offset_to_iso(base_time, float(start_val))
        else:
            timestamp_iso = _coerce_iso_timestamp(item.get("timestamp")) or _coerce_iso_timestamp(item.get("time"))
        if not timestamp_iso:
            timestamp_iso = _offset_to_iso(base_time, idx * 5.0)
        structured.append(
            {
                "speaker": speaker,
                "message": message,
                "timestamp": {"$date": timestamp_iso},
            }
        )

    return structured


def _generate_analysis_outputs(transcript_text: str) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "keywords": [],
        "mql_assessment": None,
        "sentiment_analysis": None,
        "customer_rating": None,
        "call_type": None,
        "summary": "",
        "vehicle_tags": {},
        "contact_extraction": {"name": "", "email": ""},
    }

    if not transcript_text.strip():
        return defaults

    model = (settings.OPENAI_INSIGHTS_MODEL or "").strip() or "gpt-4o-mini"
    spec = (
        "Return a JSON object with the following keys and formats: "
        "keywords -> array of distinct strings; "
        "mql_assessment -> number 1-10; "
        "sentiment_analysis -> number 1-10; "
        "customer_rating -> number 1-10; "
        "call_type -> one of ['High Score','Hot Lead','Customer Issue','General Inquiry','Follow Up','Other']; "
        "summary -> string <= 100 characters; "
        "vehicle_tags -> object mapping lowercase vehicle terms to their frequency counts as strings; "
        "contact_extraction -> object with keys name and email (empty string if missing)."
    )
    system_prompt = (
        "You analyze van-related sales calls." +
        " " + spec +
        " Strictly follow the requested format for each field."
    )
    user_prompt = (
        "Transcript:\n" + transcript_text[:12000] +
        "\n\nEnsure outputs respect the specified formats and keep arrays deduplicated."
    )

    raw_text = _call_openai_json(
        model=model,
        system_prompt=system_prompt,
        user_content=user_prompt,
        enforce_json_object=True,
    )

    if not raw_text:
        return defaults

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return defaults

    return {
        "keywords": _coerce_str_list(parsed.get("keywords")),
        "mql_assessment": _coerce_float(parsed.get("mql_assessment")),
        "sentiment_analysis": _coerce_float(parsed.get("sentiment_analysis")),
        "customer_rating": _coerce_float(parsed.get("customer_rating")),
        "call_type": _coerce_string(parsed.get("call_type")),
        "summary": _coerce_string(parsed.get("summary")),
        "vehicle_tags": _coerce_tag_map(parsed.get("vehicle_tags")),
        "contact_extraction": _coerce_contact(parsed.get("contact_extraction")),
    }


def _extract_segments(transcript: Any) -> List[Dict[str, Any]]:
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


def _coerce_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        # Attempt to parse JSON array
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return _coerce_str_list(parsed)
        except json.JSONDecodeError:
            pass
        return [value.strip()]
    return []


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    cleaned = str(value).strip()
    return cleaned or None


def _coerce_tag_map(value: Any) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if isinstance(value, dict):
        for key, val in value.items():
            k = str(key).strip().lower()
            if not k:
                continue
            if isinstance(val, (int, float)):
                result[k] = str(int(val)) if float(val).is_integer() else str(val)
            else:
                result[k] = str(val).strip()
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return _coerce_tag_map(parsed)
        except json.JSONDecodeError:
            pass
    return result


def _coerce_contact(value: Any) -> Dict[str, str]:
    name = ""
    email = ""
    if isinstance(value, dict):
        name = _coerce_string(value.get("name")) or ""
        email = _coerce_string(value.get("email")) or ""
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return _coerce_contact(parsed)
        except json.JSONDecodeError:
            pass
    return {"name": name, "email": email}


def _offset_to_iso(base_time: datetime, offset_seconds: float) -> str:
    timestamp = base_time + timedelta(seconds=max(offset_seconds, 0.0))
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_iso_timestamp(value: Any) -> Optional[str]:
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return None


def _call_openai_json(
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    enforce_json_object: bool,
    temperature: float = 0.3,
) -> str:
    client = get_openai_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        kwargs: Dict[str, Any] = {
            "model": model,
            "input": messages,
            "temperature": temperature,
        }
        if enforce_json_object:
            kwargs["response_format"] = {"type": "json_object"}
        response = client.responses.create(**kwargs)
        text = _extract_output_text(response)
        if text:
            return text
    except TypeError as exc:
        logger.debug("Responses.create type error: %s", exc)
    except Exception as exc:
        logger.warning("Responses API failed (%s). Falling back to chat completions.", exc)

    # Fallback to chat completions
    try:
        chat_response = client.chat.completions.create(  # type: ignore[attr-defined]
            model=model,
            messages=[
                {"role": "system", "content": system_prompt + " Return strict JSON only."},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
        )
        if chat_response.choices:
            return chat_response.choices[0].message.content or ""
    except Exception as exc:
        logger.error("Chat completions fallback failed: %s", exc)
    return ""


def _extract_output_text(response: Any) -> str:
    try:
        return response.output[0].content[0].text  # type: ignore[index]
    except (AttributeError, IndexError, KeyError):
        return getattr(response, "output_text", "")


def _stringify_insight(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [item for item in (_stringify_insight(v).strip() for v in value) if item]
        return "\n".join(parts)
    if isinstance(value, dict):
        parts = []
        for key, val in value.items():
            val_str = _stringify_insight(val)
            if val_str:
                parts.append(f"{key}: {val_str}")
        return "\n".join(parts)
    return str(value)


def transcribe_from_url(audio_url: str) -> TranscriptionResult:
    temp_path = _download_audio_to_tempfile(audio_url)
    try:
        return _transcribe_from_path(temp_path)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def transcribe_from_file_path(path: str) -> TranscriptionResult:
    return _transcribe_from_path(path)


def _status_name(status_obj) -> str:
    if isinstance(status_obj, str):
        return status_obj
    try:
        return status_obj.name
    except AttributeError:
        return str(status_obj)
