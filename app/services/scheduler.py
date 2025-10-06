import logging
from typing import Optional
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
        # self._register_jobs()
        
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
        
       # Process 50 calls every 30 minutes
        # 500 calls/day = ~21 calls/hour = ~50 calls per 2.5 hours
        # Running every 30 min with 50 calls = 2,400 calls/day capacity (more than enough)
        self.scheduler.add_job(
            func=lambda: process_ringcentral_calls(batch_size=50),
            trigger=IntervalTrigger(minutes=10),
            id="process_calls",
            name="Process RingCentral Calls",
            replace_existing=True,
            max_instances=1  # Don't run if previous job is still running
        )
        
        logger.info("📅 Scheduled: Process 50 calls every 30 minutes")


        
        logger.info("Cron jobs registered")


# Global scheduler instance
scheduler = SchedulerService()