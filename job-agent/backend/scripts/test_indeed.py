"""
scripts/test_indeed.py

Quick test script to verify the Indeed scraper works.
Run this inside the backend Docker container.

Usage:
    docker compose exec backend python scripts/test_indeed.py
"""

import sys
import os

# Make sure imports resolve from /app
sys.path.insert(0, "/app")

import structlog
from agents.indeed_scraper import IndeedScraper

log = structlog.get_logger()


def main():
    # These match what's in your resume_profile.yaml
    KEYWORDS = "software engineer python"
    LOCATION = "Toronto, ON"
    MAX_JOBS = 5  # Keep small for testing

    log.info("Starting Indeed scraper test", keywords=KEYWORDS, location=LOCATION)

    with IndeedScraper(headless=True) as scraper:
        # Step 1: scrape raw jobs
        raw_jobs = scraper.scrape(
            keywords=KEYWORDS,
            location=LOCATION,
            max_jobs=MAX_JOBS,
        )

        log.info("Scrape complete", raw_jobs_found=len(raw_jobs))

        # Print what we got
        for i, job in enumerate(raw_jobs, 1):
            print(f"\n--- Job {i} ---")
            print(f"  Title:    {job.get('title')}")
            print(f"  Company:  {job.get('company')}")
            print(f"  Location: {job.get('location')}")
            print(f"  URL:      {job.get('url')}")
            desc = job.get("description_raw", "")
            print(f"  Desc:     {desc[:150]}...")

        # Step 2: save to database
        if raw_jobs:
            new, skipped = scraper.save_jobs(raw_jobs)
            print(f"\n✓ Saved to DB — new: {new}, skipped: {skipped}")
        else:
            print("\n⚠ No jobs scraped — Indeed may have changed their HTML")
            print("  This is normal — scrapers need occasional maintenance")


if __name__ == "__main__":
    main()