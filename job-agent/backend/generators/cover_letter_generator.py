"""
generators/cover_letter_generator.py

Generates tailored cover letters for each job using Groq.

Input:  Job (with parsed description) + resume profile
Output: .txt file saved to /app/output/cover_letters/
        GeneratedDocument record saved to DB
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import structlog
import yaml
from groq import Groq
from ulid import ULID

from config.settings import get_settings
from db.models import DocumentType, GeneratedDocument, Job
from db.session import get_db_session

logger = structlog.get_logger(__name__)
settings = get_settings()

PROFILE_PATH = Path("/app/config/resume_profile.yaml")
OUTPUT_DIR = Path("/app/output/cover_letters")

SYSTEM_PROMPT = """
You are an expert cover letter writer. Write professional, compelling cover letters
that are specific to the job and company. Be concise — 3-4 paragraphs maximum.
Do not use generic phrases like 'I am writing to express my interest'.
Do not include placeholders like [Your Name] or [Date] — use the actual information provided.
Write in first person. Output only the cover letter text, nothing else.
""".strip()

USER_PROMPT_TEMPLATE = """
Write a cover letter for this job application.

Candidate information:
Name: {name}
Email: {email}
Location: {location}
Summary: {summary}

Experience:
{experience}

Key skills: {skills}

Job details:
Company: {company}
Role: {title}
Location: {job_location}
Job description summary: {job_summary}
Required skills: {required_skills}

Write a tailored cover letter that:
1. Opens with a specific hook related to the company or role
2. Highlights 2-3 most relevant experiences that match the requirements
3. Shows genuine interest in this specific company
4. Closes with a clear call to action
""".strip()


class CoverLetterGenerator:

    def __init__(self):
        self.client = Groq(api_key=settings.groq_api_key)
        self.model = settings.groq_model_strong if hasattr(settings, 'groq_model_strong') else settings.groq_model
        self.log = logger.bind(component="CoverLetterGenerator")
        self.profile = self._load_profile()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def generate_for_job(self, job: Job) -> str | None:
        """
        Generate a cover letter for a job and save it to disk and DB.
        Returns the file path, or None if generation failed.
        """
        if not job.description_parsed:
            self.log.warning("Job has no parsed description", job_id=job.id)
            return None

        prompt = self._build_prompt(job)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=1000,
            )

            cover_letter_text = response.choices[0].message.content.strip()
            file_path = self._save_to_file(job, cover_letter_text)
            self._save_to_db(job, file_path, prompt)

            self.log.info(
                "Cover letter generated",
                job_id=job.id,
                title=job.title,
                file_path=str(file_path),
            )
            return str(file_path)

        except Exception as e:
            self.log.error("Cover letter generation failed", job_id=job.id, error=str(e))
            return None

    # ── Private ───────────────────────────────────────────────────────────────

    def _build_prompt(self, job: Job) -> str:
        personal = self.profile.get("personal", {})
        parsed = job.description_parsed or {}

        # Format experience bullets
        experience_lines = []
        for exp in self.profile.get("experience", [])[:2]:  # top 2 roles
            experience_lines.append(
                f"- {exp['title']} at {exp['company']} ({exp['start']} to {exp['end']})"
            )
            for bullet in exp.get("bullets", [])[:2]:
                experience_lines.append(f"  • {bullet}")

        # Flatten skills
        skills = self.profile.get("skills", {})
        all_skills = (
            skills.get("core", []) +
            skills.get("proficient", [])[:5]
        )

        return USER_PROMPT_TEMPLATE.format(
            name=personal.get("name", ""),
            email=personal.get("email", ""),
            location=personal.get("location", ""),
            summary=self.profile.get("summary", ""),
            experience="\n".join(experience_lines),
            skills=", ".join(all_skills),
            company=job.company,
            title=job.title,
            job_location=job.location or "Not specified",
            job_summary=parsed.get("summary", job.title),
            required_skills=", ".join(parsed.get("required_skills", [])[:8]),
        )

    def _save_to_file(self, job: Job, text: str) -> Path:
        safe_company = re.sub(r'[^\w\-]', '_', job.company)[:30]
        safe_title = re.sub(r'[^\w\-]', '_', job.title)[:30]
        filename = f"{job.id}_{safe_company}_{safe_title}_cover_letter.txt"
        file_path = OUTPUT_DIR / filename

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(text)

        return file_path

    def _save_to_db(self, job: Job, file_path: Path, prompt: str) -> None:
        with get_db_session() as db:
            doc = GeneratedDocument(
                id=str(ULID()),
                job_id=job.id,
                document_type=DocumentType.COVER_LETTER,
                file_path=str(file_path),
                prompt_used=prompt,
                model_used=self.model,
                created_at=datetime.now(timezone.utc),
            )
            db.add(doc)

    def _load_profile(self) -> dict:
        with open(PROFILE_PATH, "r") as f:
            return yaml.safe_load(f)