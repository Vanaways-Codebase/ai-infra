import logging
from typing import Optional
from app.core.config import settings
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class SchedulerService:
    """Simple cron scheduler service for FastAPI."""
    
    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None
        
    def start(self):
        """Start the scheduler."""
        if self.scheduler is not None:
            logger.warning("Scheduler already running")
            return
            
        self.scheduler = AsyncIOScheduler()
        
        # Register your cron jobs here
        self._register_jobs()
        
        self.scheduler.start()
        logger.info("Scheduler started")
        
    def stop(self):
        """Stop the scheduler."""
        if self.scheduler is None:
            return
            
        self.scheduler.shutdown(wait=True)
        self.scheduler = None
        logger.info("Scheduler stopped")
        
    def _register_jobs(self):
        """Register all cron jobs."""
        from app.modules.asr.cron import process_ringcentral_calls

        if settings.USE_LOCAL_WHISPER:
            # No rate limits with local Whisper!
            # Process 50 calls every 30 minutes
            CALLS_PER_BATCH = 3
            INTERVAL_MINUTES = 1
            
            logger.info("🚀 Using LOCAL Whisper - No rate limits!")
        else:
            # Azure Whisper with rate limits
            CALLS_PER_BATCH = 3
            INTERVAL_MINUTES = 2
            
            logger.info("☁️ Using AZURE Whisper - Rate limited to 3 RPM")


        # # Calculate safe interval based on rate limits
        # CALLS_PER_BATCH = 3  # Process 3 calls per batch
        # RATE_LIMIT_RPM = 3  # 3 requests per minute
        # PROCESSING_BUFFER = 1.5  # Buffer multiplier for safety

        # # Safe interval = (batch size / rate limit) * buffer
        # SAFE_INTERVAL = int((CALLS_PER_BATCH / RATE_LIMIT_RPM) * PROCESSING_BUFFER)
    

        self.scheduler.add_job(
            func=process_ringcentral_calls,
            trigger=IntervalTrigger(minutes=INTERVAL_MINUTES),
            id="process_calls",
            name="Process RingCentral Calls",
            replace_existing=True,
            max_instances=5,
            kwargs={"batch_size": CALLS_PER_BATCH} 
        )

        logger.info(f"📅 Scheduled: Process {CALLS_PER_BATCH} calls every {INTERVAL_MINUTES} minutes")
        logger.info("Cron jobs registered")

# Global scheduler instance
scheduler = SchedulerService()