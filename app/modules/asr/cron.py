from app.core.database.mongodb import db
from app.modules.asr.service import transcribe, calculate_enhanced_status
import logging
from typing import Any
from datetime import datetime
from bson import ObjectId

logger = logging.getLogger(__name__)


async def process_ringcentral_calls(batch_size: int = 10):
    """
    Process pending RingCentral calls and transcribe them.
    
    Args:
        batch_size: How many calls to process in one run (default: 10)
    """
    collection = db.get_collection("calls")
    processed = 0
    
    try:
        # Find calls that need transcription
        now = datetime.utcnow()
        current_month_start = datetime(now.year, now.month, 1)

        cursor = collection.find(
            {
            "transcriptionStatus": {"$in": ["pending", "failed"]},
            "ringCentralId": {"$exists": True, "$ne": None},
            "recordingUrl": {"$exists": True, "$ne": None},
            "createdAt": {"$gte": current_month_start},
            },
            limit=batch_size
        ).sort("createdAt", -1)  # Newest first

        # Process each call
        async for call in cursor:
            call_id = call.get('_id')
            ringcentral_id = call.get('ringCentralId')
            recording_url = call.get('recordingUrl')

            try:
                logger.info(f"Processing call: {ringcentral_id}")

                # Transcribe the audio
                transcription_result = await transcribe(url=str(recording_url))

                logger.info(f"✅ Transcription complete for: {ringcentral_id}")

                summary_value = (transcription_result.summary or transcription_result.call_summary or "").strip()
                contact_model = transcription_result.contact_extraction
                contact_data = contact_model.model_dump(exclude_none=True) if contact_model else None
                tags_payload = [
                    tag.model_dump() for tag in (transcription_result.vehicle_tags or [])
                ]
                structured_transcript = transcription_result.structured_transcript or []
                keywords = transcription_result.keywords or []
                sentiment_score = transcription_result.sentiment_analysis
                buyer_intent_reason = transcription_result.buyer_intent_reason
                buyer_intent_score = transcription_result.buyer_intent_score
                call_analysis_text = transcription_result.call_analysis
                agent_recommendation = transcription_result.agent_recommendation
                mql_score = transcription_result.mql_assessment
                rating = transcription_result.customer_rating
                call_type = transcription_result.call_type

                ### Analyze Call Enhanced Status ###

                ## Finding Call In Collection
                call_in_db = await collection.find_one({"_id": ObjectId(call_id)})
                if not call_in_db:
                    logger.warning(f"❌ Call not found in DB for ID: {call_id}")
                    continue

                ## Calculate Enhanced Status
                enhanced_status_payload = {
                    "call_status": call_in_db.get("callStatus"),
                    "missed_call": call_in_db.get("missedCall"),
                    "direction": call_in_db.get("direction"),
                    "summary": summary_value,
                    "transcription_status": "completed",
                    "recording_url": recording_url,
                    "to_number": call_in_db.get("toNumber"),
                }

                enhanced_status = await calculate_enhanced_status(enhanced_status_payload)
                logger.info(f"\n**Enhanced status for {ringcentral_id}: {enhanced_status}")
                
                # Save transcription results to database
                await collection.update_one(
                    {"_id": call_id},
                    {
                        "$set": {
                            "transcriptionStatus": "completed",
                            "summary": summary_value,
                            "callAnalysis": call_analysis_text,
                            "buyerIntent": buyer_intent_score,
                            "buyerIntentReason": buyer_intent_reason,
                            "agentRecommendation": agent_recommendation,
                            "transcription": structured_transcript,
                            "keywords": keywords,
                            "keywordStatus": "completed" if keywords else "pending",
                            "mqlScore": mql_score,
                            "sentimentScore": sentiment_score,
                            "sentimentStatus": "completed" if sentiment_score is not None else "pending",
                            "rating": rating,
                            "callType": call_type,
                            "tags": tags_payload,
                            "enhancedStatus": enhanced_status,
                            "metadata": call.get("metadata", {}) or {
                                "contact": contact_data,
                            }
                        }
                    }
                )

                # Update customer information if available
                customer_id = call.get("customerId")
                if customer_id:
                    customer_collection = db.get_collection("customers")
                    contact = contact_data or {}
                    
                    await customer_collection.update_one(
                        {"_id": customer_id},
                        {
                            "$set": {
                                "name": contact.get("name", "Unknown"),
                                "email": contact.get("email", "Unknown"),
                                "address": contact.get("address", ""),

                            }
                        }
                    )
                
                processed += 1
                
            except Exception as call_error:
                logger.error(f"❌ Failed to process call {ringcentral_id}: {call_error}")
                
                # Mark this call as failed
                await collection.update_one(
                    {"_id": call_id},
                    {"$set": {
                        "transcriptionStatus": "failed",
                        "transcriptionError": str(call_error)
                    }}
                )
        
        logger.info(f"Batch complete. Processed {processed} calls.")
        return processed
        
    except Exception as e:
        logger.error(f"Error in batch processing: {e}")
        return 0   
