#Takes scrapped test from a job posting and sends it to OpenAI to extrav and structure data 
#Ouput is a clean json file that the scoring engine can work with 

#Breaks down posting for to compare portfolio 

#reacs raw desc from data base 
#sends openAI wirth a carefully designed promtop that askss to only give nack the json
#parese response and saves it back to the jobs descrpition_parsed 
#updates job status from new to scored 

import json
import re

import structlog
from openai import OpenAI

from config.settings import get_settings
from db.models import Job
from db.session import get_db_session
from groq import Groq

logger = structlog.get_logger(__name__)
settings = get_settings()


# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are a job description parser. Extract structured information from job postings.
You must respond with ONLY valid JSON — no markdown, no explanation, no code blocks.
If a field cannot be determined, use null for strings and empty arrays for lists.
""".strip()

USER_PROMPT_TEMPLATE = """
Parse this job description and return a JSON object with exactly these fields:

{{
    "role_type": "string — one of: engineering, ml_ai, data, devops, product, design, other",
    "seniority": "string — one of: internship, junior, mid, senior, staff, principal, unknown",
    "required_skills": ["list of required technical skills"],
    "preferred_skills": ["list of nice-to-have skills"],
    "tech_stack": ["specific technologies, frameworks, tools mentioned"],
    "years_experience_min": "integer or null — minimum years required",
    "employment_type": "string — one of: full-time, part-time, contract, internship, unknown",
    "remote_type": "string — one of: remote, hybrid, onsite, unknown",
    "visa_sponsorship": "boolean — true if sponsorship is offered",
    "summary": "string — 2-3 sentence summary of the role"
}}

Job title: {title}
Company: {company}

Job description:
{description}
""".strip()


# ── Parser class ──────────────────────────────────────────────────────────────

class JDParser:

    def __init__(self):
        self.client = Groq(api_key=settings.groq_api_key)
        self.model = settings.groq_model
        self.log = logger.bind(component="JDParser")

    def parse_job(self, job: Job) -> dict | None:
        """
        Parse a single job's description using OpenAI.
        Returns the parsed dict, or None if parsing failed.
        """
        if not job.description_raw:
            self.log.warning("Job has no description, skipping", job_id=job.id)
            return None

        # Truncate very long descriptions to stay within token limits
        description = job.description_raw[:6000]

        prompt = USER_PROMPT_TEMPLATE.format(
            title=job.title,
            company=job.company,
            description=description,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,          # deterministic output for parsing tasks
                max_tokens=1000,
            )

            raw_output = response.choices[0].message.content.strip()
            parsed = self._parse_response(raw_output)

            self.log.info(
                "Parsed job",
                job_id=job.id,
                title=job.title,
                seniority=parsed.get("seniority"),
                skills_count=len(parsed.get("required_skills", [])),
            )
            return parsed

        except Exception as e:
            self.log.error("Failed to parse job", job_id=job.id, error=str(e))
            return None

    def parse_unparsed_jobs(self, limit: int = 50) -> tuple[int, int]:
        """
        Finds all jobs with no description_parsed and parses them.
        Called by the nightly pipeline after scraping.

        Returns:
            (success_count, failed_count)
        """
        success = 0
        failed = 0

        with get_db_session() as db:
            # Find jobs that have raw descriptions but haven't been parsed yet
            jobs = (
                db.query(Job)
                .filter(
                    Job.description_parsed.is_(None),
                    Job.description_raw.isnot(None),
                    Job.description_raw != "",
                )
                .limit(limit)
                .all()
            )

            self.log.info("Jobs to parse", count=len(jobs))

            for job in jobs:
                parsed = self.parse_job(job)
                if parsed:
                    job.description_parsed = parsed
                    success += 1
                else:
                    failed += 1

        self.log.info("Parsing complete", success=success, failed=failed)
        return success, failed

    # ── Private ───────────────────────────────────────────────────────────────

    def _parse_response(self, raw: str) -> dict:
        """
        Safely parse the LLM's JSON response.
        Handles cases where the model wraps output in markdown code blocks.
        """
        # Strip markdown code blocks if present
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            self.log.error("JSON parse failed", error=str(e), raw=raw[:200])
            # Return a minimal valid structure rather than crashing
            return {
                "role_type": "other",
                "seniority": "unknown",
                "required_skills": [],
                "preferred_skills": [],
                "tech_stack": [],
                "years_experience_min": None,
                "employment_type": "unknown",
                "remote_type": "unknown",
                "visa_sponsorship": False,
                "summary": "",
            }