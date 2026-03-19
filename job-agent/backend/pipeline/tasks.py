#Celery applicstion and task definition 
#The actual pipeline logic loves ain nightly_pipeline.py
#These tasls are thin wraoppers that celery knows how to schedule 


from celery import Celery
from celery.schedules import crontab

from config.settings import get_settings

settings = get_settings()

# ── Celery app ────────────────────────────────────────────────────────────────

celery_app = Celery(
    "job_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["pipeline.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,
)

# ── Beat schedule ─────────────────────────────────────────────────────────────

celery_app.conf.beat_schedule = {
    "nightly-pipeline": {
        "task": "pipeline.tasks.run_nightly_pipeline",
        "schedule": crontab(
            hour=str(settings.pipeline_cron_hour),
            minute=str(settings.pipeline_cron_minute),
        ),
    },
}

# ── Tasks ─────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="pipeline.tasks.run_nightly_pipeline",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
def run_nightly_pipeline(self):
    """
    Master task — runs the full pipeline.
    bind=True gives access to self.retry() on failure.
    """
    import structlog
    logger = structlog.get_logger(__name__)

    try:
        logger.info("Pipeline task started", task_id=self.request.id)
        from pipeline.nightly_pipeline import NightlyPipeline
        result = NightlyPipeline().run()
        logger.info("Pipeline task completed", result=result)
        return result
    except Exception as exc:
        logger.error("Pipeline task failed", error=str(exc))
        raise self.retry(exc=exc)