"""Main scheduler application using APScheduler.

Run with: python -m betting_app.scheduler.app
"""

import logging
import signal
import sys
import os
import traceback
from concurrent.futures import ThreadPoolExecutor as _TPE, Future
from functools import wraps

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

from betting_app.core.db import database_url
from betting_app.services.automation_service import start_run, finish_run, cleanup_stale_runs

from .registry import registry, register_all_tasks

logger = logging.getLogger(__name__)

# Default timeout (seconds) for individual task runs.
# Tasks that exceed this are marked failed and the thread is abandoned.
_DEFAULT_TASK_TIMEOUT = 3600  # 1 hour


def execute_task(task_id: str, *args, **kwargs):
    """Execute a task by ID with run tracking.
    
    This is the main entry point for APScheduler jobs. It looks up the task
    in the registry and wraps its execution with automation_runs tracking.
    """
    from .registry import registry
    task = registry.get(task_id)
    if not task:
        logger.error(f"Task {task_id} not found in registry")
        return

    run_id = None
    try:
        run_id = start_run(
            run_type=task_id,
            trigger_source="apscheduler",
        )
        logger.info(f"[{task_id}] Started automation run #{run_id}")

        # Run the task function
        result = task.func(*args, **kwargs)

        # Determine status from result dict
        if isinstance(result, dict):
            success = result.get("success", True)
            status = "completed" if success else "failed"
            error = result.get("error") if not success else None
        else:
            status = "completed"
            error = None
        
        finish_run(run_id, status=status, error=error)
        logger.info(f"[{task_id}] Run #{run_id} finished: {status}")
        return result
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exc()
        logger.error(f"[{task_id}] Run #{run_id} failed: {error_msg}\n{tb}")
        if run_id:
            try:
                finish_run(run_id, status="failed", error=error_msg)
            except Exception:
                logger.error(f"[{task_id}] Failed to mark run #{run_id} as failed")
        raise


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
    """Add all registered tasks to the scheduler.
    
    Each task is scheduled to call execute_task(task_id, ...).
    """
    
    for task in registry.list_enabled():
        if task.interval_minutes:
            scheduler.add_job(
                execute_task,
                trigger="interval",
                minutes=task.interval_minutes,
                id=task.id,
                name=task.name,
                args=(task.id,) + task.args,
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
                    execute_task,
                    trigger="cron",
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                    id=task.id,
                    name=task.name,
                    args=(task.id,) + task.args,
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
    
    # Clean up any stale 'running' runs from a previous crashed scheduler
    stale_count = cleanup_stale_runs(max_age_hours=2)
    if stale_count:
        logger.warning(f"Cleaned up {stale_count} stale 'running' automation run(s)")
    
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
