"""
scripts/test_pipeline.py

Runs the full nightly pipeline once manually.
Use this to test the entire chain end to end.

Usage:
    docker compose exec backend python scripts/test_pipeline.py
"""

import sys
sys.path.insert(0, "/app")

from pipeline.nightly_pipeline import NightlyPipeline


def main():
    print("Starting full pipeline run...")
    print("This will scrape, parse, score, and generate documents.")
    print()

    pipeline = NightlyPipeline()
    stats = pipeline.run()

    print()
    print("Pipeline complete. Results:")
    print(f"  Jobs scraped:    {stats['jobs_scraped']}")
    print(f"  New jobs:        {stats['jobs_new']}")
    print(f"  Jobs scored:     {stats['jobs_scored']}")
    print(f"  Tier 2 queued:   {stats['queued_tier2']}")
    print(f"  Tier 3 queued:   {stats['queued_tier3']}")
    print(f"  Skipped:         {stats['skipped']}")
    print(f"  Failed:          {stats['failed']}")


if __name__ == "__main__":
    main()