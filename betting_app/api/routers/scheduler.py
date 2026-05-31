"""Router: /api/scheduler — task listing, status, and manual triggers."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from betting_app.api.deps import get_db, query_df, query_one
from betting_app.api.schemas import (
    SchedulerJobResponse,
    SchedulerTaskResponse,
    SchedulerTriggerResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scheduler", tags=["scheduler"])

# Background executor for manual task triggers
_executor = ThreadPoolExecutor(max_workers=2)
_running_tasks: dict[str, datetime] = {}
_lock = threading.Lock()


def _get_registry():
    """Lazy import to avoid circular imports and heavy loading at startup."""
    from betting_app.scheduler.registry import registry, register_all_tasks

    # Ensure tasks are registered (idempotent)
    if not registry.list_all():
        register_all_tasks()
    return registry


@router.get("/tasks", response_model=list[SchedulerTaskResponse])
def list_tasks():
    """List all registered task definitions."""
    reg = _get_registry()
    tasks = []
    for t in reg.list_all():
        tasks.append(
            SchedulerTaskResponse(
                id=t.id,
                name=t.name,
                description=t.description,
                interval_minutes=t.interval_minutes,
                cron_trigger=t.cron_trigger,
                enabled=t.enabled,
            )
        )
    return tasks


@router.get("/jobs", response_model=list[SchedulerJobResponse])
def list_jobs(db=Depends(get_db)):
    """List scheduled jobs from APScheduler job store + recent automation runs."""
    # Read from apscheduler_jobs table (APScheduler serializes job state here)
    jobs_raw = query_df(
        db,
        """
        SELECT id, next_run_time
        FROM apscheduler_jobs
        ORDER BY next_run_time
        """,
    )

    # Build a map of job_id -> next_run_time
    job_map = {}
    for row in jobs_raw:
        jid = row["id"]
        nrt = row.get("next_run_time")
        # APScheduler stores next_run_time as epoch float in some backends
        if isinstance(nrt, (int, float)):
            nrt = datetime.fromtimestamp(nrt, tz=timezone.utc).isoformat()
        elif isinstance(nrt, datetime):
            nrt = nrt.isoformat()
        job_map[jid] = nrt

    # Get recent automation runs for last_run info
    recent_runs = query_df(
        db,
        """
        SELECT run_type, status, started_at, finished_at, error
        FROM automation_runs
        ORDER BY started_at DESC
        LIMIT 50
        """,
    )

    # Build last_run map per task type
    last_run_map: dict[str, dict] = {}
    for run in recent_runs:
        rt = run.get("run_type", "")
        if rt not in last_run_map:
            last_run_map[rt] = run

    # Merge registry tasks with job store data
    reg = _get_registry()
    results = []
    for t in reg.list_all():
        next_run = job_map.get(t.id)
        last_run_info = last_run_map.get(t.id) or last_run_map.get(
            t.id.replace("scrape_", "scrape_")
        )

        last_run_at = None
        last_run_status = None
        if last_run_info:
            la = last_run_info.get("finished_at") or last_run_info.get("started_at")
            if isinstance(la, datetime):
                last_run_at = la.isoformat()
            elif la:
                last_run_at = str(la)
            last_run_status = last_run_info.get("status")

        with _lock:
            is_running = t.id in _running_tasks

        results.append(
            SchedulerJobResponse(
                id=t.id,
                name=t.name,
                enabled=t.enabled,
                next_run_time=next_run,
                last_run_at=last_run_at,
                last_run_status=last_run_status,
                is_running=is_running,
            )
        )

    return results


@router.post("/trigger/{task_id}", response_model=SchedulerTriggerResponse)
def trigger_task(task_id: str):
    """Manually trigger a task to run in the background."""
    reg = _get_registry()
    task = reg.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    with _lock:
        if task_id in _running_tasks:
            raise HTTPException(
                status_code=409, detail=f"Task '{task_id}' is already running"
            )
        _running_tasks[task_id] = datetime.now(timezone.utc)

    def _run():
        try:
            logger.info(f"Manual trigger: {task_id}")
            task.func(*task.args, **task.kwargs)
            logger.info(f"Manual trigger completed: {task_id}")
        except Exception as exc:
            logger.error(f"Manual trigger failed: {task_id}: {exc}")
        finally:
            with _lock:
                _running_tasks.pop(task_id, None)

    _executor.submit(_run)

    return SchedulerTriggerResponse(
        task_id=task_id,
        status="started",
        message=f"Task '{task_id}' triggered in background",
    )


@router.get("/runs", response_model=list[dict])
def list_recent_runs(limit: int = 20, db=Depends(get_db)):
    """List recent automation runs."""
    return query_df(
        db,
        """
        SELECT id, run_type, status, started_at, finished_at, error,
               EXTRACT(EPOCH FROM (finished_at::timestamp - started_at::timestamp)) AS duration_seconds
        FROM automation_runs
        ORDER BY started_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )


@router.get("/runs/{run_id}/commands", response_model=list[dict])
def list_run_commands(run_id: int, db=Depends(get_db)):
    """List commands for a specific automation run."""
    return query_df(
        db,
        """
        SELECT id, command, status, started_at, finished_at, error
        FROM automation_commands
        WHERE run_id = :run_id
        ORDER BY started_at
        """,
        {"run_id": run_id},
    )
