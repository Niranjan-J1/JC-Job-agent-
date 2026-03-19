#Orchestrate the full pipeline from end to end 
#Each phrase is a stub for now, we fill them in as we build each module


import structlog
from datetime import datetime, timezone

from python_ulid import ULID

from config.settings import get_settings
from db.models import PipelineRun, PipelineRunStatus
from db.session import get_db_session

logger = structlog.get_logger(__name__)
settings = get_settings()


class NightlyPipeline:

    def run(self) -> dict:
        run_id = str(ULID())
        log = logger.bind(run_id=run_id)
        log.info("Pipeline starting")

        with get_db_session() as db:
            run = PipelineRun(id=run_id)
            db.add(run)
            db.flush()

            try:
                stats = self._execute(log)
                self._finish_run(db, run, PipelineRunStatus.COMPLETED, stats)
                log.info("Pipeline completed", **stats)
                return stats

            except Exception as exc:
                log.error("Pipeline failed", error=str(exc))
                self._finish_run(db, run, PipelineRunStatus.FAILED, error=str(exc))
                raise

    def _execute(self, log) -> dict:
        stats = {
            "jobs_scraped": 0,
            "jobs_new": 0,
            "jobs_scored": 0,
            "applied_tier1": 0,
            "queued_tier2": 0,
            "queued_tier3": 0,
            "skipped": 0,
            "failed": 0,
        }

        # Each phase will be filled in as we build the modules
        log.info("Phase 1: scraping — coming in next step")
        log.info("Phase 2: parsing — coming soon")
        log.info("Phase 3: scoring — coming soon")
        log.info("Phase 4: generation — coming soon")
        log.info("Phase 5: application — coming soon")

        return stats

    def _finish_run(
        self,
        db,
        run: PipelineRun,
        status: PipelineRunStatus,
        stats: dict = None,
        error: str = None,
    ) -> None:
        run.status = status
        run.ended_at = datetime.now(timezone.utc)
        if stats:
            for key, val in stats.items():
                if hasattr(run, key):
                    setattr(run, key, val)
        if error:
            run.error_log = error