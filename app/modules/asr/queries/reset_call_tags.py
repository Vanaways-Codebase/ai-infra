import asyncio
import logging
from typing import Any, Dict, Optional

from app.core.database.mongodb import db

logger = logging.getLogger(__name__)


async def set_empty_tags(filter_query: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """
    Update calls so the `tags` field becomes an empty list.

    Args:
        filter_query: Optional MongoDB filter deciding which calls to update.
            Defaults to all documents when omitted.

    Returns:
        Number of modified call documents.
    """
    query: Dict[str, Any] = filter_query or {}

    disconnect_after = False
    if db.database is None:
        await db.connect()
        disconnect_after = True

    try:
        calls_collection = db.get_collection("calls")
        # Snapshot the current number of documents that carry non-empty tags
        pre_update_count = await calls_collection.count_documents(
            {
                **query,
                "tags": {
                    "$exists": True,
                    "$not": {"$size": 0},  # tags field exists and is a non-empty array
                },
            }
        )

        result = await calls_collection.update_many(query, {"$set": {"tags": []}})
        post_update_count = await calls_collection.count_documents(
            {
                **query,
                "tags": {
                    "$exists": True,
                    "$not": {"$size": 0},
                },
            }
        )
        logger.info(
            "Cleared tags for %d call(s) (matched=%d) matching filter: %s",
            result.modified_count,
            result.matched_count,
            query,
        )
        logger.info(
            "Non-empty tags before update: %d, after update: %d",
            pre_update_count,
            post_update_count,
        )
        return {
            "matched": result.matched_count,
            "modified": result.modified_count,
            "non_empty_before": pre_update_count,
            "non_empty_after": post_update_count,
        }
    finally:
        if disconnect_after:
            await db.disconnect()


if __name__ == "__main__":
    # Run as a script: python -m app.modules.asr.queries.reset_call_tags
    stats = asyncio.run(set_empty_tags())
    print(
        "Matched: {matched}, Modified: {modified}, "
        "non-empty before: {non_empty_before}, non-empty after: {non_empty_after}".format(
            **stats
        )
    )
