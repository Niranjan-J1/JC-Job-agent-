"""
agents/base_scraper.py

Base class for all job scraping agents.
Each scraper (Indeed, LinkedIn, WaterlooWorks) inherits from this.

Responsibilities:
  - Launch and configure Playwright with stealth settings
  - Provide save_jobs() to persist scraped jobs and deduplicate
  - Wrap page interactions with retry logic
  - Clean up browser resources on exit
"""

import random
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

import structlog
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from ulid import ULID
from tenacity import retry, stop_after_attempt, wait_exponential

from db.models import Job, JobStatus
from db.session import get_db_session

logger = structlog.get_logger(__name__)

# Realistic user agents — rotate to avoid fingerprinting
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]


class BaseScraper(ABC):
    """
    Abstract base class for all job scrapers.

    Usage:
        class IndeedScraper(BaseScraper):
            def scrape(self, keywords, location, max_jobs):
                # implement Indeed-specific logic here
                ...
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.log = logger.bind(scraper=self.__class__.__name__)
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    # ── Browser lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the browser and configure stealth settings."""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1920,1080",
            ],
        )
        self._context = self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=random.choice(USER_AGENTS),
            # Pretend to be a real browser — these headers are sent on every request
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
        )
        # Remove the webdriver property that sites use to detect automation
        self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        self.log.info("Browser started")

    def stop(self) -> None:
        """Close the browser and clean up resources."""
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self.log.info("Browser stopped")

    def new_page(self) -> Page:
        """Opens a new browser tab."""
        if not self._context:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._context.new_page()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    def scrape(
        self,
        keywords: str,
        location: str,
        max_jobs: int = 25,
    ) -> list[dict]:
        """
        Scrape job postings and return a list of raw job dicts.

        Each dict must contain at minimum:
            {
                "title": str,
                "company": str,
                "url": str,           # unique identifier for deduplication
                "location": str,
                "description_raw": str,
                "source": str,        # e.g. "indeed", "linkedin"
            }
        """
        ...

    # ── Database persistence ──────────────────────────────────────────────────

    def save_jobs(self, raw_jobs: list[dict]) -> tuple[int, int]:
        """
        Save scraped jobs to the database.
        Skips jobs whose URL already exists (deduplication).

        Returns:
            (new_count, skipped_count)
        """
        new_count = 0
        skipped_count = 0

        with get_db_session() as db:
            for raw in raw_jobs:
                url = raw.get("url", "").strip()
                if not url:
                    self.log.warning("Job missing URL, skipping", title=raw.get("title"))
                    skipped_count += 1
                    continue

                # Deduplication — check if we've seen this URL before
                existing = db.query(Job).filter(Job.url == url).first()
                if existing:
                    skipped_count += 1
                    continue

                job = Job(
                    id=str(ULID()),
                    source=raw.get("source", "unknown"),
                    company=raw.get("company", "Unknown"),
                    title=raw.get("title", "Unknown"),
                    url=url,
                    location=raw.get("location"),
                    employment_type=raw.get("employment_type"),
                    description_raw=raw.get("description_raw"),
                    status=JobStatus.NEW,
                    scraped_at=datetime.now(timezone.utc),
                )
                db.add(job)
                new_count += 1

        self.log.info(
            "Jobs saved",
            new=new_count,
            skipped=skipped_count,
        )
        return new_count, skipped_count

    # ── Helpers ───────────────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def safe_goto(self, page: Page, url: str, wait_until: str = "domcontentloaded") -> None:
        """
        Navigate to a URL with automatic retry on failure.
        Waits for the DOM to load, then adds a small random delay
        to simulate human browsing behaviour.
        """
        self.log.debug("Navigating", url=url)
        page.goto(url, wait_until=wait_until, timeout=30000)
        # Random human-like delay between 1.5 and 3.5 seconds
        page.wait_for_timeout(random.randint(1500, 3500))

    def random_delay(self, page: Page, min_ms: int = 500, max_ms: int = 2000) -> None:
        """Pause for a random duration to simulate human reading speed."""
        page.wait_for_timeout(random.randint(min_ms, max_ms))