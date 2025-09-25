import json
import logging
import mimetypes
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from app.core.config import settings
from app.core.openai_client import get_openai_client


logger = logging.getLogger(__name__)


STRUCTURED_TRANSCRIPT_MODEL = "gpt-4.1-2025-04-14"
# Prefer a higher-context model when the base request overflows the token window
STRUCTURED_TRANSCRIPT_FALLBACK_MODEL = "gpt-4.1"


@dataclass
class TranscriptionResult:
    status: str
    text: str
    confidence: Optional[float] = None
    id: Optional[str] = None
    call_summary: Optional[str] = None
    call_analysis: Optional[str] = None
    buyer_intent: Optional[str] = None
    buyer_intent_score: Optional[float] = None
    buyer_intent_reason: Optional[str] = None
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
    buyer_intent_reason = _stringify_insight(insights.get("buyer_intent_reason"))
    buyer_intent_score = _coerce_float(insights.get("buyer_intent_score"))
    agent_reco = _stringify_insight(insights.get("agent_recommendation"))
    return TranscriptionResult(
        status="completed",
        text=text,
        confidence=None,
        id=getattr(transcript, "id", None),
        call_summary=summary,
        call_analysis=analysis,
        buyer_intent=buyer_intent_reason,
        buyer_intent_score=buyer_intent_score,
        buyer_intent_reason=buyer_intent_reason,
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
        return {
            "summary": "",
            "analysis": "",
            "buyer_intent_score": 0,
            "buyer_intent_reason": "",
            "agent_recommendation": "",
        }

    model = (settings.OPENAI_INSIGHTS_MODEL or "").strip() or "gpt-4o-mini"
    # Keep prompt concise to control latency and cost while ensuring structured output
    prompt = (
        "You are an expert sales analyst. Given the transcript, decide whether the customer expresses interest "
        "in purchasing or continuing a service. Return JSON with keys: summary (string, 3-5 bullet sentences), "
        "analysis (string highlighting tone, objections, pivotal moments), buyer_intent_score (integer 1-10), "
        "buyer_intent_reason (string explaining the score and explicitly mention if a sale or renewal occurs), "
        "agent_recommendation (string with next best actions). When the call contains a confirmed purchase, "
        "renewal, or strong buying signals, the score must be 8-10. If the caller declines, requests support only, "
        "or shows no interest, the score must be 1-3. Use 4-7 for uncertain or mixed interest."
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
        data = json.loads(raw_text)
        if isinstance(data, dict):
            if "buyer_intent_score" in data:
                try:
                    data["buyer_intent_score"] = int(data["buyer_intent_score"])
                except (TypeError, ValueError):
                    data["buyer_intent_score"] = 0
            return data
    except json.JSONDecodeError:
        return {
            "summary": raw_text,
            "analysis": "",
            "buyer_intent_score": 0,
            "buyer_intent_reason": "",
            "agent_recommendation": "",
        }


def _generate_structured_transcript(transcript_text: str, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not transcript_text.strip():
        return []

    system_prompt = (
        "You transform call transcripts into structured JSON. Return a JSON array where each element has the "
        "keys speaker, message, start, end. Speaker must be either agent or customer. If unsure, infer from "
        "context but keep the best guess. Start and end should be the segment start/end in seconds if provided; "
        "otherwise estimate monotonically increasing floats. Message should contain the cleaned utterance text."
    )

    primary_payload = {
        "segments": segments[:120] if segments else [],
        "transcript": transcript_text[:12000],
        "instructions": "Label each utterance as agent or customer and preserve chronological order, and if call gets hold or music or anything else, note that as well.",
    }

    raw_text, error = _call_openai_json_with_error(
        model=STRUCTURED_TRANSCRIPT_MODEL,
        system_prompt=system_prompt,
        user_content=json.dumps(primary_payload, ensure_ascii=False),
        enforce_json_object=False,
    )

    if not raw_text and _is_context_length_error(error):
        logger.info("Structured transcript request exceeded base context; retrying with fallback model.")
        fallback_payload = {
            "segments": segments,
            "transcript": transcript_text,
            "instructions": primary_payload["instructions"],
        }
        raw_text, error = _call_openai_json_with_error(
            model=STRUCTURED_TRANSCRIPT_FALLBACK_MODEL,
            system_prompt=system_prompt,
            user_content=json.dumps(fallback_payload, ensure_ascii=False),
            enforce_json_object=False,
        )

    parsed_items: List[Dict[str, Any]] = []
    if raw_text:
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            if "utterances" in parsed and isinstance(parsed["utterances"], list):
                parsed = parsed["utterances"]
            else:
                parsed = [value for value in parsed.values() if isinstance(value, dict)]
        if isinstance(parsed, list):
            parsed_items = [item for item in parsed if isinstance(item, dict)]

    parsed_items = _expand_combined_dialogue(parsed_items)

    structured = _build_structured_entries(parsed_items)
    if structured:
        return structured

    structured_from_segments = _build_structured_entries(_segment_items(segments))
    if structured_from_segments:
        return structured_from_segments

    return _build_structured_entries(_transcript_text_items(transcript_text))


def _build_structured_entries(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    base_time = datetime.now(timezone.utc)
    structured: List[Dict[str, Any]] = []
    turn_index = 0
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        raw_message = item.get("message")
        if raw_message is None:
            raw_message = item.get("text")
        message = _stringify_insight(raw_message).strip()
        if not message:
            continue

        default_speaker = str(item.get("speaker", "")).strip().lower()
        if default_speaker not in {"agent", "customer"}:
            default_speaker = "agent" if (turn_index % 2 == 0) else "customer"

        splits = _split_message_into_turns(message, default_speaker)
        if not splits:
            splits = [(default_speaker, message)]

        start_val = item.get("start")
        base_timestamp_iso = None
        if not isinstance(start_val, (int, float)):
            base_timestamp_iso = _coerce_iso_timestamp(item.get("timestamp")) or _coerce_iso_timestamp(item.get("time"))
            if not base_timestamp_iso and isinstance(item.get("timestamp"), dict):
                ts = item.get("timestamp", {})
                base_timestamp_iso = _coerce_iso_timestamp(ts.get("$date")) or _coerce_iso_timestamp(ts.get("iso"))

        for split_idx, (speaker, turn_message) in enumerate(splits):
            normalized_speaker = speaker if speaker in {"agent", "customer"} else default_speaker
            if not normalized_speaker:
                normalized_speaker = "agent" if (turn_index % 2 == 0) else "customer"

            if isinstance(start_val, (int, float)):
                offset = float(start_val) + split_idx * 2.5
                timestamp_iso = _offset_to_iso(base_time, offset)
            elif base_timestamp_iso and split_idx == 0:
                timestamp_iso = base_timestamp_iso
            else:
                timestamp_iso = _offset_to_iso(base_time, turn_index * 5.0)

            structured.append(
                {
                    "speaker": normalized_speaker,
                    "message": turn_message,
                    "timestamp": {"$date": timestamp_iso},
                }
            )
            turn_index += 1

    return structured


def _segment_items(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for segment in segments or []:
        if not isinstance(segment, dict):
            continue
        message = _stringify_insight(segment.get("text")).strip()
        if not message:
            continue
        item: Dict[str, Any] = {
            "message": message,
            "start": segment.get("start"),
        }
        if "speaker" in segment:
            item["speaker"] = segment.get("speaker")
        items.append(item)
    return items


def _transcript_text_items(transcript_text: str) -> List[Dict[str, Any]]:
    cleaned = transcript_text.strip()
    if not cleaned:
        return []
    lines = [line.strip() for line in cleaned.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        lines = [cleaned]
    items: List[Dict[str, Any]] = []
    for idx, line in enumerate(lines):
        items.append(
            {
                "speaker": "agent" if idx % 2 == 0 else "customer",
                "message": line,
                "start": float(idx * 5),
            }
        )
    return items


def _expand_combined_dialogue(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    expanded: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        raw_message = item.get("message")
        if raw_message is None:
            raw_message = item.get("text")
        text = _stringify_insight(raw_message).strip()
        if not text:
            continue

        splits = _split_message_into_turns(text, str(item.get("speaker", "")))
        if splits and len(splits) > 1:
            for speaker, message in splits:
                expanded.append({"speaker": speaker, "message": message})
            continue

        if "\n" in text:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if len(lines) > 1:
                for line in lines:
                    expanded.append({"speaker": item.get("speaker"), "message": line})
                continue

        new_item = dict(item)
        new_item["message"] = text
        expanded.append(new_item)

    return expanded


def _split_message_into_turns(message: str, default_speaker: str) -> List[Tuple[str, str]]:
    message = message.strip()
    if not message:
        return []

    pattern = re.compile(r"\b(agent|customer)\s*[:\-]\s*", re.IGNORECASE)
    matches = list(pattern.finditer(message))
    if matches:
        turns: List[Tuple[str, str]] = []
        for idx, match in enumerate(matches):
            speaker = match.group(1).lower()
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(message)
            turn_text = message[start:end].strip()
            if turn_text:
                turns.append((speaker, turn_text))
        if turns:
            return turns

    normalized_default = default_speaker.lower().strip()
    if "\n" in message:
        lines = [line.strip() for line in message.splitlines() if line.strip()]
        if len(lines) > 1:
            speaker = normalized_default or "agent"
            return [(speaker, line) for line in lines]

    sentences = _split_into_sentences(message)
    if len(sentences) > 1:
        base_speaker = normalized_default or "agent"
        turns: List[Tuple[str, str]] = []
        for idx, sentence in enumerate(sentences):
            speaker = base_speaker if idx % 2 == 0 else ("customer" if base_speaker == "agent" else "agent")
            turns.append((speaker, sentence))
        return turns

    return [((normalized_default or "agent"), message)]


def _split_into_sentences(message: str) -> List[str]:
    pattern = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
    chunks = [chunk.strip() for chunk in pattern.split(message) if chunk.strip()]
    if len(chunks) <= 1:
        return chunks
    combined: List[str] = []
    buffer = ""
    for chunk in chunks:
        if len(chunk) < 10 and buffer:
            buffer = f"{buffer} {chunk}".strip()
        else:
            if buffer:
                combined.append(buffer)
            buffer = chunk
    if buffer:
        combined.append(buffer)
    return combined


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
        "short_summary -> string <= 100 characters; "
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


def _call_openai_json_with_error(
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    enforce_json_object: bool,
    temperature: float = 0.3,
) -> Tuple[str, Optional[BaseException]]:
    client = get_openai_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    last_error: Optional[BaseException] = None
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
            return text, None
    except TypeError as exc:
        logger.debug("Responses.create type error: %s", exc)
        last_error = exc
    except Exception as exc:
        logger.warning("Responses API failed (%s). Falling back to chat completions.", exc)
        last_error = exc

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
            return chat_response.choices[0].message.content or "", None
    except Exception as exc:
        logger.error("Chat completions fallback failed: %s", exc)
        return "", exc
    return "", last_error


def _call_openai_json(
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    enforce_json_object: bool,
    temperature: float = 0.3,
) -> str:
    text, _ = _call_openai_json_with_error(
        model=model,
        system_prompt=system_prompt,
        user_content=user_content,
        enforce_json_object=enforce_json_object,
        temperature=temperature,
    )
    return text


def _is_context_length_error(error: Optional[BaseException]) -> bool:
    if not error:
        return False
    message = str(error).lower()
    if "maximum context length" in message or "context length" in message or "too many tokens" in message:
        return True
    code = getattr(error, "code", "")
    if isinstance(code, str) and "context" in code.lower():
        return True
    return False


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
