"""
scripts/test_generators.py

Tests resume and cover letter generation against the scored test job.

Usage:
    docker compose exec backend python scripts/test_generators.py
"""

import sys
sys.path.insert(0, "/app")

from generators.cover_letter_generator import CoverLetterGenerator
from generators.resume_generator import ResumeGenerator
from db.models import Job
from db.session import get_db_session


def main():
    with get_db_session() as db:
        job = db.query(Job).filter(
            Job.description_parsed.isnot(None)
        ).first()

        if not job:
            print("No parsed jobs found. Run test_parser.py first.")
            return

        print(f"Generating documents for: {job.title} at {job.company}")
        print()

        # Generate cover letter
        print("--- Generating cover letter ---")
        cl_gen = CoverLetterGenerator()
        cl_path = cl_gen.generate_for_job(job)
        if cl_path:
            print(f"✓ Cover letter saved to: {cl_path}")
            with open(cl_path) as f:
                print("\nPreview:")
                print(f.read()[:500])
        else:
            print("✗ Cover letter generation failed")

        print()

        # Generate resume
        print("--- Generating resume ---")
        res_gen = ResumeGenerator()
        res_path = res_gen.generate_for_job(job)
        if res_path:
            print(f"✓ Resume saved to: {res_path}")
            with open(res_path) as f:
                print("\nPreview:")
                print(f.read()[:500])
        else:
            print("✗ Resume generation failed")


if __name__ == "__main__":
    main()