"""
scripts/test_parser.py

Tests the job description parser against jobs already in the database.

Usage:
    docker compose exec backend python scripts/test_parser.py
"""

import sys
sys.path.insert(0, "/app")

import json
from parsers.jd_parser import JDParser
from db.models import Job
from db.session import get_db_session

def main():
    parser = JDParser()

    with get_db_session() as db:
        # Grab first job with a description
        job = db.query(Job).filter(
            Job.description_raw.isnot(None),
            Job.description_raw != "",
        ).first()

        if not job:
            print("No jobs with descriptions found.")
            print("Run test_indeed.py first, then make sure descriptions are being saved.")
            return

        print(f"Parsing: {job.title} at {job.company}")
        print(f"Description preview: {job.description_raw[:200]}...")
        print()

        result = parser.parse_job(job)

        if result:
            print("✓ Parsed successfully:")
            print(json.dumps(result, indent=2))

            # Save back to DB
            job.description_parsed = result
            print("\n✓ Saved to database")
        else:
            print("✗ Parsing failed")

if __name__ == "__main__":
    main()