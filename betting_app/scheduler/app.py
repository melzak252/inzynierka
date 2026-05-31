"""Main scheduler application using APScheduler.

Run with: python -m betting_app.scheduler.app
"""

import logging
import signal
import sys
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

from betting_app.core.db import database_url

from .registry import registry, register_all_tasks

logger = logging.getLogger(__name__)


def create_scheduler() -> BlockingScheduler:
    """Create and configure the APScheduler instance."""
    
    # Job store - persist jobs in PostgreSQL (or SQLite fallback)
    jobstores = {
        "default": SQLAlchemyJobStore(url=database_url()),
    }
    
    # Executors
    executors = {
        "default": ThreadPoolExecutor(max_workers=3),
    }
    
    # Job defaults
    job_defaults = {
        "coalesce": True,       # Combine missed runs into one
        "max_instances": 1,     # Only one instance of each job at a time
        "misfire_grace_time": 300,  # 5 min grace period for missed jobs
    }
    
    scheduler = BlockingScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone="UTC",
    )
    
    return scheduler


def schedule_tasks(scheduler: BlockingScheduler):
    """Add all registered tasks to the scheduler."""
    
    for task in registry.list_enabled():
        if task.interval_minutes:
            scheduler.add_job(
                task.func,
                trigger="interval",
                minutes=task.interval_minutes,
                id=task.id,
                name=task.name,
                args=task.args,
                kwargs=task.kwargs,
                replace_existing=True,
            )
            logger.info(
                f"Scheduled: {task.id} every {task.interval_minutes}min"
            )
        elif task.cron_trigger:
            # Parse cron expression (minute hour day month day_of_week)
            parts = task.cron_trigger.split()
            if len(parts) == 5:
                scheduler.add_job(
                    task.func,
                    trigger="cron",
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                    id=task.id,
                    name=task.name,
                    args=task.args,
                    kwargs=task.kwargs,
                    replace_existing=True,
                )
                logger.info(
                    f"Scheduled: {task.id} cron={task.cron_trigger}"
                )
            else:
                logger.error(f"Invalid cron for {task.id}: {task.cron_trigger}")
        else:
            logger.warning(f"Task {task.id} has no trigger, skipping")


def main():
    """Main entry point for the scheduler."""
    
    # Logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    logger.info("=" * 60)
    logger.info("Betting App Scheduler starting")
    logger.info(f"Database: {database_url()[:50]}...")
    logger.info("=" * 60)
    
    # Register all tasks
    register_all_tasks()
    
    # Create scheduler
    scheduler = create_scheduler()
    
    # Schedule tasks
    schedule_tasks(scheduler)
    
    # Graceful shutdown
    def shutdown(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        scheduler.shutdown(wait=False)
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    
    # Print scheduled jobs
    jobs = scheduler.get_jobs()
    logger.info(f"Total scheduled jobs: {len(jobs)}")
    for job in jobs:
        logger.info(f"  - {job.id}: trigger={job.trigger}")
    
    # Start
    logger.info("Scheduler started. Press Ctrl+C to exit.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
