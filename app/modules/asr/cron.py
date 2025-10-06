from app.core.database.mongodb import db
from app.modules.asr.service import transcribe
import logging
from typing import Any

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
        cursor = collection.find(
            {
                "transcriptionStatus": "pending",
                "ringCentralId": {"$exists": True, "$ne": None},
                "recordingUrl": {"$exists": True, "$ne": None},
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
                result_dict = transcription_result.dict()
                
                logger.info(f"✅ Transcription complete for: {ringcentral_id}")

                # Save transcription results to database
                await collection.update_one(
                    {"_id": call_id},
                    {
                        "$set": {
                            "transcriptionStatus": "completed",
                            "summary": result_dict.get("call_summary"),
                            "callAnalysis": result_dict.get("call_analysis"),
                            "buyerIntent": result_dict.get("buyer_intent_score"),
                            "buyerIntentReason": result_dict.get("buyer_intent_reason"),
                            "agentRecommendation": result_dict.get("agent_recommendation"),
                            "transcription": result_dict.get("structured_transcript"),
                            "keywords": result_dict.get("keywords"),
                            "keywordStatus": "completed" if result_dict.get("keywords") else "pending",
                            "mqlScore": result_dict.get("mql_assessment"),
                            "sentimentScore": result_dict.get("sentiment_analysis"),
                            "sentimentStatus": "completed" if result_dict.get("sentiment_analysis") is not None else "pending",
                            "rating": result_dict.get("customer_rating"),
                            "callType": result_dict.get("call_type"),
                            "tags": result_dict.get("vehicle_tags"),
                            "metadata": call.get("metadata", {}) or {
                                "contact": result_dict.get("contact_extraction"),
                            }
                        }
                    }
                )

                # Update customer information if available
                customer_id = call.get("customerId")
                if customer_id:
                    customer_collection = db.get_collection("customers")
                    contact = result_dict.get("contact_extraction", {})
                    
                    await customer_collection.update_one(
                        {"_id": customer_id},
                        {
                            "$set": {
                                "name": contact.get("name", "Unknown"),
                                "email": contact.get("email", "Unknown"),
                                "address": contact.get("address", "Unknown"),
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