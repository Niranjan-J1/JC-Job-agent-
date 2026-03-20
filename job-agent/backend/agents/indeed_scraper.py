"""
agents/indeed_scraper.py

Scrapes job postings from Indeed.com.
Extracts description from the search results page directly
rather than navigating to each job detail page, which triggers
Indeed's bot detection.
"""

import random
from urllib.parse import quote_plus

import structlog
from bs4 import BeautifulSoup
from playwright.sync_api import Page

from agents.base_scraper import BaseScraper

logger = structlog.get_logger(__name__)

INDEED_BASE_URL = "https://www.indeed.com"


class IndeedScraper(BaseScraper):

    SOURCE = "indeed"

    def scrape(
        self,
        keywords: str,
        location: str,
        max_jobs: int = 25,
    ) -> list[dict]:
        self.log.info("Starting Indeed scrape", keywords=keywords, location=location)
        jobs = []
        page = self.new_page()

        try:
            results_page = 0

            while len(jobs) < max_jobs:
                start = results_page * 10
                url = self._build_search_url(keywords, location, start)

                self.log.info("Scraping results page", page=results_page + 1)
                self.safe_goto(page, url)

                # Click the first job card to load description in the side panel
                new_jobs = self._extract_jobs_from_results(page, max_jobs - len(jobs))

                if not new_jobs:
                    self.log.info("No more jobs found, stopping")
                    break

                jobs.extend(new_jobs)
                self.log.info("Extracted jobs from page", count=len(new_jobs))

                results_page += 1
                self.random_delay(page, min_ms=3000, max_ms=6000)

        except Exception as e:
            self.log.error("Indeed scrape failed", error=str(e))
        finally:
            page.close()

        self.log.info("Indeed scrape complete", total_jobs=len(jobs))
        return jobs

    def _build_search_url(self, keywords: str, location: str, start: int = 0) -> str:
        q = quote_plus(keywords)
        l = quote_plus(location)
        return f"{INDEED_BASE_URL}/jobs?q={q}&l={l}&start={start}&sort=date"

    def _extract_jobs_from_results(self, page: Page, limit: int) -> list[dict]:
        """
        Extracts jobs by clicking each card and reading the
        description from Indeed's side panel — avoids navigating
        to individual job pages which triggers bot detection.
        """
        jobs = []

        try:
            page.wait_for_selector('[data-jk]', timeout=10000)
        except Exception:
            self.log.warning("No job cards found on page")
            return jobs

        soup = BeautifulSoup(page.content(), "lxml")
        cards = soup.select('[data-jk]')
        self.log.info("Found job cards", count=len(cards))

        for card in cards[:limit]:
            try:
                job_key = card.get("data-jk")
                if not job_key:
                    continue

                # Extract title
                title_el = card.select_one(
                    '[data-testid="job-title"] span, .jobTitle span, h2 span'
                )
                title = title_el.get_text(strip=True) if title_el else "Unknown"

                # Extract company
                company_el = card.select_one(
                    '[data-testid="company-name"], '
                    '.companyName, '
                    'span[class*="company"], '
                    '[class*="EmployerName"], '
                    'a[data-testid="company-name"]'
                )
                company = company_el.get_text(strip=True) if company_el else "Unknown"

                # Extract location
                location_el = card.select_one(
                    '[data-testid="text-location"], '
                    '.companyLocation, '
                    'div[class*="location"], '
                    '[class*="Location"]'
                )
                location = location_el.get_text(strip=True) if location_el else ""

                

                # Click the card to load description in the side panel
                try:
                    page.click(f'[data-jk="{job_key}"]', timeout=5000)
                    self.random_delay(page, min_ms=1500, max_ms=3000)

                    # Try to read description from side panel
                    description = ""
                    try:
                        page.wait_for_selector(
                            '#jobDescriptionText, '
                            '[data-testid="jobsearch-jobDescriptionText"], '
                            '.jobsearch-jobDescriptionText',
                            timeout=5000,
                        )
                        updated_soup = BeautifulSoup(page.content(), "lxml")
                        desc_el = updated_soup.select_one(
                            '#jobDescriptionText, '
                            '[data-testid="jobsearch-jobDescriptionText"], '
                            '.jobsearch-jobDescriptionText'
                        )
                        if desc_el:
                            description = desc_el.get_text(separator="\n", strip=True)
                    except Exception:
                        # Side panel didn't load — save job without description
                        self.log.debug("Side panel timeout, saving without description",
                                      job_key=job_key)

                except Exception as e:
                    self.log.debug("Could not click card", job_key=job_key, error=str(e))

                jobs.append({
                    "source": self.SOURCE,
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": f"{INDEED_BASE_URL}/viewjob?jk={job_key}",
                    "description_raw": description,
                    "employment_type": None,
                })

            except Exception as e:
                self.log.warning("Failed to parse card", error=str(e))
                continue

        return jobs