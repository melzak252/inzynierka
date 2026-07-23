"""ML/retraining scheduler tasks."""

import logging
from datetime import datetime

from sqlalchemy import text

from betting_app.core.db import get_session

from .scrape import _run_module

logger = logging.getLogger(__name__)


def run_weekly_retraining() -> dict:
    """Run the production ML weekly retraining pipeline.

    The pipeline trains candidate models on historical finished matches,
    performs walk-forward validation, saves an immutable dataset/model artifact,
    and registers the model version as a shadow candidate.
    """
    logger.info("Starting weekly ML retraining")
    start = datetime.utcnow()

    success = _run_module(
        "betting_app.ml.pipelines.weekly_retrain_cli",
        args=[
            "--model-name",
            "Operational-Retrained-Tabular",
            "--status-on-success",
            "shadow",
            "--json",
        ],
        timeout=1800,
    )

    duration = (datetime.utcnow() - start).total_seconds()
    logger.info(f"Weekly ML retraining: {'OK' if success else 'FAIL'} ({duration:.1f}s)")

    return {
        "success": success,
        "duration_s": duration,
        "timestamp": start.isoformat(),
    }


def run_shadow_inference() -> dict:
    """Run inference for registered shadow ML models.

    This does not promote or replace the current production/thesis model. It
    only writes active `canonical_predictions` rows for models registered with
    `status='shadow'`, so they become visible in match detail/history views.
    """
    logger.info("Starting shadow ML inference")
    start = datetime.utcnow()

    success = _run_module(
        "betting_app.ml.inference.cli",
        args=["--status", "shadow", "--json"],
        timeout=600,
    )

    duration = (datetime.utcnow() - start).total_seconds()
    logger.info(f"Shadow ML inference: {'OK' if success else 'FAIL'} ({duration:.1f}s)")

    return {
        "success": success,
        "duration_s": duration,
        "timestamp": start.isoformat(),
    }


def run_thesis_model_healthcheck() -> dict:
    """Run a read-only rolling evaluation of the current thesis model.

    The healthcheck intentionally uses ``--no-register``: it should verify
    recent model-vs-market quality and emit logs, not create/promote model
    versions.  This gives the scheduler a lightweight recurring guardrail for
    the production model without affecting inference state.
    """
    logger.info("Starting thesis model healthcheck")
    start = datetime.utcnow()

    success = _run_module(
        "betting_app.ml.pipelines.evaluate_existing_model",
        args=[
            "--model-name",
            "Sym-Cal LR-ElasticNet-W20-Binomial",
            "--model-version",
            "exp-039",
            "--days-back",
            "90",
            "--no-register",
            "--json",
        ],
        timeout=900,
    )

    duration = (datetime.utcnow() - start).total_seconds()
    logger.info(f"Thesis model healthcheck: {'OK' if success else 'FAIL'} ({duration:.1f}s)")

    return {
        "success": success,
        "duration_s": duration,
        "timestamp": start.isoformat(),
    }


def run_scheduler_healthcheck() -> dict:
    """Check recent scheduler/scraper health and fail loudly on regressions.

    This is a lightweight alerting primitive: APScheduler records the run in
    ``automation_runs``.  If any critical task failed recently or a bookmaker
    has stale odds snapshots, this task returns ``success=False`` so the failure
    becomes visible in logs and the system status dashboard.
    """
    logger.info("Starting scheduler healthcheck")
    start = datetime.utcnow()
    failures: list[str] = []

    with get_session() as session:
        failed_runs = session.execute(
            text(
                """
                SELECT f.run_type, f.status, f.started_at, f.error
                FROM automation_runs f
                WHERE f.started_at >= NOW() - INTERVAL '6 hours'
                  AND f.status = 'failed'
                  AND f.run_type IN ('scrape_sts', 'prediction_pipeline', 'shadow_ml_inference', 'thesis_model_healthcheck')
                  AND NOT EXISTS (
                      SELECT 1
                      FROM automation_runs s
                      WHERE s.run_type = f.run_type
                        AND s.status = 'completed'
                        AND s.started_at > f.started_at
                  )
                ORDER BY f.started_at DESC
                LIMIT 10
                """
            ),
        ).mappings().all()
        for row in failed_runs:
            failures.append(
                f"recent failed run: {row['run_type']} at {row['started_at']} ({row.get('error') or 'no error'})"
            )

        stale_scrapes = session.execute(
            text(
                """
                SELECT b.name, MAX(os.scraped_at) AS last_scraped_at
                FROM bookmakers b
                LEFT JOIN odds_snapshots os ON os.bookmaker_id = b.id
                WHERE b.is_active = 1
                  AND b.name IN ('sts', 'betclic', 'superbet', 'efortuna', 'betfan', 'totalbet', 'lebull')
                GROUP BY b.name
                HAVING MAX(os.scraped_at) IS NULL
                    OR MAX(os.scraped_at) < NOW() - INTERVAL '8 hours'
                ORDER BY last_scraped_at NULLS FIRST
                """
            )
        ).mappings().all()
        for row in stale_scrapes:
            failures.append(f"stale bookmaker snapshots: {row['name']} last_scraped_at={row['last_scraped_at']}")

    duration = (datetime.utcnow() - start).total_seconds()
    success = not failures
    if success:
        logger.info(f"Scheduler healthcheck: OK ({duration:.1f}s)")
    else:
        logger.error("Scheduler healthcheck: FAIL (%s) failures=%s", f"{duration:.1f}s", failures)

    return {
        "success": success,
        "duration_s": duration,
        "timestamp": start.isoformat(),
        "failures": failures,
    }
