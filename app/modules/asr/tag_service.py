import logging
from typing import Any, Dict, List, Optional, Sequence

from bson import ObjectId

from app.core.database.mongodb import db
from .service import _format_vehicle_tags

logger = logging.getLogger(__name__)


async def update_call_tags(
    call_id: Optional[str] = None,
    *,
    ring_central_id: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Fetch a call document and update its `tags` field to the structured format.

    Args:
        call_id: MongoDB _id of the call as a string.
        ring_central_id: Optional RingCentral recording identifier to locate the call.
            When both identifiers are supplied, call_id takes precedence.

    Returns:
        The newly formatted list of tag dictionaries, or None if the call is not found.

    Raises:
        ValueError: If neither identifier is provided or the call_id is malformed.
    """

    if call_id is None and ring_central_id is None:
        raise ValueError("Either call_id or ring_central_id must be provided")

    query: Dict[str, Any]
    if call_id is not None:
        try:
            query = {"_id": ObjectId(call_id)}
        except Exception as exc:  # pragma: no cover - defensive guardrail
            raise ValueError(f"Invalid call_id supplied: {call_id}") from exc
    else:
        query = {"ringCentralId": ring_central_id}

    disconnect_after = False
    if db.database is None:
        await db.connect()
        disconnect_after = True

    try:
        calls_collection = db.get_collection("calls")
        call_document = await calls_collection.find_one(query)
        if not call_document:
            logger.warning("Call not found for query: %s", query)
            return None

        existing_tags = call_document.get("tags")
        raw_tags = _coerce_raw_tags(existing_tags)
        if not raw_tags and not existing_tags:
            logger.info("Call %s has no tags to update.", call_document.get("_id"))
            await calls_collection.update_one(
                {"_id": call_document["_id"]}, {"$set": {"tags": []}}
            )
            return []

        transcript_text = _build_transcript_text(call_document)
        formatted_tags = _format_vehicle_tags(transcript_text, raw_tags)

        await calls_collection.update_one(
            {"_id": call_document["_id"]},
            {"$set": {"tags": formatted_tags}},
        )
        logger.info(
            "Updated tags for call %s to new format. Total tags: %d",
            call_document.get("_id"),
            len(formatted_tags),
        )
        return formatted_tags
    finally:
        if disconnect_after:
            await db.disconnect()


def _coerce_raw_tags(tags: Any) -> Sequence[Any]:
    """Translate stored tag structures into the raw format expected by _format_vehicle_tags."""
    if not tags:
        return []

    coerced: List[Any] = []
    if isinstance(tags, dict):
        for tag, count in tags.items():
            tag_text = str(tag).strip()
            if not tag_text:
                continue
            count_value = _safe_positive_int(count, default=1)
            coerced.append({tag_text: count_value})
        return coerced

    if isinstance(tags, list):
        for entry in tags:
            if isinstance(entry, dict):
                tag_text = str(entry.get("tag") or entry.get("name") or "").strip()
                count_value = entry.get("count")
                if tag_text and count_value is not None:
                    coerced.append({tag_text: _safe_positive_int(count_value, default=1)})
                    continue
                # Fall back to raw dict semantics (might already be {"ford": 3})
                if len(entry) == 1:
                    tag_key, tag_value = next(iter(entry.items()))
                    coerced.append({str(tag_key).strip(): _safe_positive_int(tag_value, default=1)})
                    continue
            elif isinstance(entry, str):
                tag_text = entry.strip()
                if tag_text:
                    coerced.append({tag_text: 1})
    return coerced


def _build_transcript_text(call_document: Dict[str, Any]) -> str:
    """Best-effort aggregation of transcript text from stored call data."""
    transcript_entries = call_document.get("transcription")
    if isinstance(transcript_entries, list):
        parts: List[str] = []
        for entry in transcript_entries:
            if isinstance(entry, dict):
                text = entry.get("message") or entry.get("text")
                if text:
                    parts.append(str(text))
            elif isinstance(entry, str):
                parts.append(entry)
        if parts:
            return " ".join(parts)

    transcription_result = call_document.get("transcriptionResult")
    if isinstance(transcription_result, dict):
        text = transcription_result.get("text")
        if isinstance(text, str):
            return text

    summary_text = call_document.get("summary")
    if isinstance(summary_text, str):
        return summary_text

    return ""


def _safe_positive_int(value: Any, *, default: int = 1) -> int:
    """Convert a value to a positive int, returning default when coercion fails."""
    try:
        integer_value = int(value)
        if integer_value > 0:
            return integer_value
    except (TypeError, ValueError):
        pass
    return default
