"""Composable ML pipeline entrypoints.

These functions are intentionally plain Python so they can be called from Docker,
cron, a scheduler task, or later wrapped as Kedro nodes without changing the
business logic.
"""

from betting_app.ml.pipelines.evaluation import EvaluationPipelineConfig, EvaluationPipelineResult, run_evaluation_pipeline

__all__ = [
    "EvaluationPipelineConfig",
    "EvaluationPipelineResult",
    "run_evaluation_pipeline",
]
