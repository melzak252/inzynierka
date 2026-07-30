"""Task registry - central place to define all scheduled tasks."""

from dataclasses import dataclass, field
from typing import Callable, Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class TaskDefinition:
    """Definition of a scheduled task."""
    id: str
    name: str
    func: Callable
    args: tuple = field(default_factory=tuple)  # Arguments to pass to func
    kwargs: dict = field(default_factory=dict)  # Keyword arguments
    cron_trigger: Optional[str] = None  # Cron expression
    interval_minutes: Optional[int] = None  # Interval in minutes
    description: str = ""
    enabled: bool = True


class TaskRegistry:
    """Registry of all available tasks."""
    
    def __init__(self):
        self._tasks: dict[str, TaskDefinition] = {}
    
    def register(self, task: TaskDefinition):
        """Register a new task."""
        if task.id in self._tasks:
            logger.warning(f"Task {task.id} already registered, overwriting")
        self._tasks[task.id] = task
        logger.info(f"Registered task: {task.id} ({task.name})")
    
    def get(self, task_id: str) -> Optional[TaskDefinition]:
        """Get a task by ID."""
        return self._tasks.get(task_id)
    
    def list_all(self) -> list[TaskDefinition]:
        """List all registered tasks."""
        return list(self._tasks.values())
    
    def list_enabled(self) -> list[TaskDefinition]:
        """List all enabled tasks."""
        return [t for t in self._tasks.values() if t.enabled]


# Global registry instance
registry = TaskRegistry()


def register_all_tasks():
    """Register all tasks in the system."""
    from .tasks import scrape, predict, maintenance, ml
    
    # Scrape tasks - run at :55 every 2 hours (e.g., 9:55, 11:55, 13:55...)
    # Most matches start at full hours, so this captures odds close to start time
    for bookmaker in scrape.BOOKMAKERS:
        registry.register(TaskDefinition(
            id=f"scrape_{bookmaker}",
            name=f"Scrape {bookmaker.title()}",
            func=scrape.scrape_bookmaker,
            args=(bookmaker,),
            cron_trigger="55 */2 * * *",  # At minute 55, every 2nd hour
            description=f"Scrape odds from {bookmaker}",
            enabled=True
        ))
    
    # Prediction pipeline - run at :10 every 2 hours (15 min after scraping)
    registry.register(TaskDefinition(
        id="prediction_pipeline",
        name="Prediction Pipeline",
        func=predict.run_prediction_pipeline,
        cron_trigger="10 */2 * * *",  # At minute 10, every 2nd hour
        description="Run full prediction pipeline",
        enabled=True
    ))

    # Shadow ML inference - after the main prediction pipeline
    registry.register(TaskDefinition(
        id="shadow_ml_inference",
        name="Shadow ML Inference",
        func=ml.run_shadow_inference,
        cron_trigger="20 */2 * * *",  # At minute 20, every 2nd hour
        description="Run registered shadow ML models without replacing production predictions",
        enabled=True
    ))
    
    # Maintenance tasks (heavy cycle) - every 6 hours
    registry.register(TaskDefinition(
        id="refresh_golgg",
        name="Refresh GolGG Data",
        func=maintenance.refresh_golgg,
        interval_minutes=360,  # Every 6 hours
        description="Refresh GolGG match data",
        enabled=True
    ))
    
    registry.register(TaskDefinition(
        id="rebuild_ratings",
        name="Rebuild Team Ratings",
        func=maintenance.rebuild_ratings,
        interval_minutes=360,  # Every 6 hours
        description="Rebuild team Elo ratings",
        enabled=True
    ))
    
    registry.register(TaskDefinition(
        id="rebuild_features",
        name="Rebuild Rolling Features",
        func=maintenance.rebuild_rolling_features,
        interval_minutes=360,  # Every 6 hours
        description="Rebuild W20 rolling features",
        enabled=True
    ))

    # Weekly ML retraining - Sunday early morning UTC
    registry.register(TaskDefinition(
        id="weekly_ml_retraining",
        name="Weekly ML Retraining",
        func=ml.run_weekly_retraining,
        cron_trigger="30 3 * * 0",  # Sunday 03:30 UTC
        description="Train/evaluate/register shadow ML model candidate",
        enabled=True
    ))

    # Production model healthcheck - once per day after the heavy maintenance cycle
    registry.register(TaskDefinition(
        id="thesis_model_healthcheck",
        name="Thesis Model Healthcheck",
        func=ml.run_thesis_model_healthcheck,
        cron_trigger="45 4 * * *",  # Daily 04:45 UTC
        description="Read-only 90-day evaluation of the current thesis model vs market",
        enabled=True
    ))

    # Champion embedding refresh - daily after GOL.GG/rating maintenance.
    # Writes current artifact plus monthly walk-forward snapshots for the
    # embedding diagnostics page.
    registry.register(TaskDefinition(
        id="refresh_champion_role_embeddings",
        name="Refresh Champion Role Embeddings",
        func=ml.refresh_champion_role_embeddings,
        cron_trigger="20 5 * * *",  # Daily 05:20 UTC
        description="Rebuild champion-role embeddings and walk-forward snapshots",
        enabled=True
    ))

    # Team/opponent embedding refresh - daily after champion embeddings.
    registry.register(TaskDefinition(
        id="refresh_team_context_embeddings",
        name="Refresh Team Context Embeddings",
        func=ml.refresh_team_context_embeddings,
        cron_trigger="35 5 * * *",  # Daily 05:35 UTC
        description="Rebuild team/opponent context embeddings and walk-forward snapshots",
        enabled=True
    ))

    # Scheduler healthcheck - frequent lightweight alerting via automation_runs
    registry.register(TaskDefinition(
        id="scheduler_healthcheck",
        name="Scheduler Healthcheck",
        func=ml.run_scheduler_healthcheck,
        cron_trigger="35 * * * *",  # Hourly at :35 UTC
        description="Check recent scheduler failures and stale bookmaker odds snapshots",
        enabled=True
    ))

    # Browser artifact cleanup - guardrail for interrupted nodriver/Chromium scrapes.
    registry.register(TaskDefinition(
        id="browser_artifact_cleanup",
        name="Browser Artifact Cleanup",
        func=scrape.cleanup_browser_artifacts,
        cron_trigger="25 * * * *",  # Hourly, after inference and before healthcheck
        description="Kill stale Chromium/nodriver processes and remove scraper temp dirs",
        enabled=True
    ))
    
    # Backfill expired matches to GOL.GG - once per day
    registry.register(TaskDefinition(
        id="backfill_expired_matches",
        name="Backfill Expired Matches to GOL.GG",
        func=maintenance.backfill_expired_matches,
        interval_minutes=1440,  # Every 24 hours
        description="Map expired canonical matches to existing GOL.GG results",
        enabled=True
    ))
    
    # Expire old matches - every 2 hours, 5 min after scraping
    registry.register(TaskDefinition(
        id="expire_matches",
        name="Expire Old Matches",
        func=maintenance.expire_matches,
        cron_trigger="0 */2 * * *",  # At minute 0, every 2nd hour
        kwargs={"grace_hours": 3},
        description="Mark matches as expired when start_time has passed (3h grace)",
        enabled=True
    ))
    
    # Horizon bootstrap analysis - once per day
    registry.register(TaskDefinition(
        id="horizon_bootstrap",
        name="Horizon Bootstrap Analysis",
        func=maintenance.run_horizon_bootstrap,
        cron_trigger="15 0 * * *",  # Daily, after Model Analysis cache refresh
        description="Run monthly block bootstrap analysis comparing models vs bookmaker per horizon bin",
        enabled=True
    ))

    # Model Analysis cache - once per day at midnight
    registry.register(TaskDefinition(
        id="model_analysis_cache",
        name="Model Analysis Cache Refresh",
        func=maintenance.refresh_model_analysis_cache,
        cron_trigger="0 0 * * *",
        description="Precompute cached horizon accuracy and CLV payloads for the Model Analysis page",
        enabled=True
    ))

    # Expire stale-seen matches - every hour
    # Catches cancelled/postponed matches that disappeared from scrapers
    registry.register(TaskDefinition(
        id="expire_stale_matches",
        name="Expire Stale-Seen Matches",
        func=maintenance.expire_stale_matches,
        cron_trigger="30 * * * *",  # At minute 30, every hour
        kwargs={"stale_seen_hours": 6},
        description="Mark matches as expired when not seen by scrapers for 6h",
        enabled=True
    ))
    
    logger.info(f"Registered {len(registry.list_all())} tasks")
