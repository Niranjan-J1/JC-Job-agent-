"""
scripts/test_scorer.py

Tests the scoring engine against the parsed test job.

Usage:
    docker compose exec backend python scripts/test_scorer.py
"""

import sys
sys.path.insert(0, "/app")

import json
from scoring.scorer import JobScorer
from db.models import Job
from db.session import get_db_session


def main():
    scorer = JobScorer()

    with get_db_session() as db:
        # Find the job we parsed earlier
        job = db.query(Job).filter(
            Job.description_parsed.isnot(None)
        ).first()

        if not job:
            print("No parsed jobs found. Run test_parser.py first.")
            return

        print(f"Scoring: {job.title} at {job.company}")
        print()

        score, reasons = scorer.score_job(job)

        print(f"Final score:     {score}")
        print(f"Matched skills:  {reasons['matched_skills']}")
        print(f"Missing skills:  {reasons['missing_skills']}")
        print(f"Bonuses:         {reasons['bonuses']}")
        print(f"Penalties:       {reasons['penalties']}")
        print()
        print("Breakdown:")
        print(json.dumps(reasons['breakdown'], indent=2))
        print()

        tier = scorer._assign_tier(score)
        print(f"Assigned tier:   {tier.value}")

        # Save to DB
        from datetime import datetime, timezone
        from db.models import JobStatus
        job.match_score = score
        job.match_reasons = reasons
        job.automation_tier = tier
        job.status = JobStatus.SCORED
        job.scored_at = datetime.now(timezone.utc)
        print("\n✓ Score saved to database")


if __name__ == "__main__":
    main()