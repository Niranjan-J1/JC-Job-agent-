"""
pipeline/nightly_pipeline.py

Orchestrates the full nightly pipeline:
  1. Scrape jobs from all sources
  2. Parse job descriptions with Groq
  3. Score jobs against resume profile
  4. Generate resume + cover letter for qualifying jobs
  5. Log results to pipeline_runs table

Each phase is isolated — a failure in one job doesn't stop the rest.
"""

import structlog
from datetime import datetime, timezone

from ulid import ULID

from config.settings import get_settings
from db.models import Job, JobStatus, PipelineRun, PipelineRunStatus
from db.session import get_db_session

logger = structlog.get_logger(__name__)
settings = get_settings()

# Search config — edit these to match your job search
SEARCH_QUERIES = [
    {"keywords": "software engineer python", "location": "Toronto, ON"},
    {"keywords": "backend engineer", "location": "Remote"},
    {"keywords": "ml engineer python", "location": "Toronto, ON"},
]

MAX_JOBS_PER_QUERY = 10  # keep low during testing, increase for production


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
                stats = self._execute(db, log)
                self._finish_run(db, run, PipelineRunStatus.COMPLETED, stats)
                log.info("Pipeline completed", **stats)
                return stats

            except Exception as exc:
                log.error("Pipeline failed", error=str(exc))
                self._finish_run(db, run, PipelineRunStatus.FAILED, error=str(exc))
                raise

    def _execute(self, db, log) -> dict:
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

        # ── Phase 1: Scrape ────────────────────────────────────────────────
        log.info("Phase 1: scraping")
        scraped, new = self._run_scrapers()
        stats["jobs_scraped"] = scraped
        stats["jobs_new"] = new
        log.info("Scraping complete", scraped=scraped, new=new)

        # ── Phase 2: Parse ─────────────────────────────────────────────────
        log.info("Phase 2: parsing")
        parsed, parse_failed = self._run_parser()
        stats["failed"] += parse_failed
        log.info("Parsing complete", parsed=parsed, failed=parse_failed)

        # ── Phase 3: Score ─────────────────────────────────────────────────
        log.info("Phase 3: scoring")
        scored, score_skipped = self._run_scorer()
        stats["jobs_scored"] = scored
        log.info("Scoring complete", scored=scored)

        # ── Phase 4: Generate documents ────────────────────────────────────
        log.info("Phase 4: generating documents")
        gen_stats = self._run_generators()
        stats["queued_tier2"] += gen_stats.get("tier2", 0)
        stats["queued_tier3"] += gen_stats.get("tier3", 0)
        stats["skipped"] += gen_stats.get("skipped", 0)
        log.info("Generation complete", **gen_stats)

        return stats

    # ── Phase implementations ─────────────────────────────────────────────────

    def _run_scrapers(self) -> tuple[int, int]:
        """Run all scrapers and return (total_scraped, new_jobs)."""
        from agents.indeed_scraper import IndeedScraper

        total_scraped = 0
        total_new = 0

        for query in SEARCH_QUERIES:
            try:
                with IndeedScraper(headless=True) as scraper:
                    raw_jobs = scraper.scrape(
                        keywords=query["keywords"],
                        location=query["location"],
                        max_jobs=MAX_JOBS_PER_QUERY,
                    )
                    total_scraped += len(raw_jobs)
                    new, _ = scraper.save_jobs(raw_jobs)
                    total_new += new

            except Exception as e:
                logger.error(
                    "Scraper failed for query",
                    query=query,
                    error=str(e),
                )

        return total_scraped, total_new

    def _run_parser(self) -> tuple[int, int]:
        """Parse all unparsed jobs. Returns (success, failed)."""
        from parsers.jd_parser import JDParser
        parser = JDParser()
        return parser.parse_unparsed_jobs(limit=50)

    def _run_scorer(self) -> tuple[int, int]:
        """Score all unscored jobs. Returns (scored, skipped)."""
        from scoring.scorer import JobScorer
        scorer = JobScorer()
        return scorer.score_unscored_jobs(limit=100)

    def _run_generators(self) -> dict:
        """
        Generate resume and cover letter for all scored jobs
        that don't have documents yet.
        Only generates for Tier 1 and Tier 2 jobs — Tier 3 is
        below threshold and not worth generating docs for.
        """
        from generators.cover_letter_generator import CoverLetterGenerator
        from generators.resume_generator import ResumeGenerator
        from db.models import AutomationTier

        stats = {"tier1": 0, "tier2": 0, "tier3": 0, "skipped": 0, "failed": 0}

        cl_gen = CoverLetterGenerator()
        res_gen = ResumeGenerator()

        with get_db_session() as db:
            # Find scored jobs that don't have documents yet
            jobs_needing_docs = (
                db.query(Job)
                .filter(
                    Job.status == JobStatus.SCORED,
                    Job.automation_tier.in_([
                        AutomationTier.TIER1,
                        AutomationTier.TIER2,
                    ]),
                )
                .all()
            )

            logger.info("Jobs needing documents", count=len(jobs_needing_docs))

            for job in jobs_needing_docs:
                try:
                    # Generate both documents
                    cl_path = cl_gen.generate_for_job(job)
                    res_path = res_gen.generate_for_job(job)

                    if cl_path and res_path:
                        tier_key = job.automation_tier.value.lower()
                        stats[tier_key] = stats.get(tier_key, 0) + 1

                        # Update job status to QUEUED
                        job.status = JobStatus.QUEUED

                    else:
                        stats["failed"] += 1

                except Exception as e:
                    logger.error(
                        "Document generation failed",
                        job_id=job.id,
                        error=str(e),
                    )
                    stats["failed"] += 1

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