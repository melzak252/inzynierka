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
    from .tasks import scrape, predict, maintenance
    
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
    
    logger.info(f"Registered {len(registry.list_all())} tasks")
