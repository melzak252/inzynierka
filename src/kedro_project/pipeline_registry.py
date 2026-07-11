"""Pipeline registry for the Kedro project."""

from kedro.pipeline import Pipeline
from kedro_project.pipelines import evaluation, weekly_retrain


def register_pipelines() -> dict[str, Pipeline]:
    """Register all pipelines for the project."""
    return {
        "__default__": Pipeline([weekly_retrain.create_pipeline(), evaluation.create_pipeline()]),
        "weekly_retrain": weekly_retrain.create_pipeline(),
        "evaluation": evaluation.create_pipeline(),
    }