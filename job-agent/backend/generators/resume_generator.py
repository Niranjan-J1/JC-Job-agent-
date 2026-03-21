"""
generators/resume_generator.py

Generates a tailored resume for each job as a .txt file.
Uses Groq to reorder and emphasize the most relevant experience
and skills for each specific job.

Output: .txt file saved to /app/output/resumes/
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
OUTPUT_DIR = Path("/app/output/resumes")

SYSTEM_PROMPT = """
You are an expert resume writer. Given a candidate's profile and a job description,
produce a tailored resume that emphasizes the most relevant skills and experience.
Output only the resume text in clean plain text format.
Use standard resume sections: Summary, Experience, Skills, Education, Projects.
Do not add information that isn't in the profile — only reorder and emphasize.
""".strip()

USER_PROMPT_TEMPLATE = """
Create a tailored resume for this job application.

TARGET JOB:
Company: {company}
Title: {title}
Required skills: {required_skills}
Job summary: {job_summary}

CANDIDATE PROFILE:
Name: {name}
Email: {email}
Phone: {phone}
Location: {location}
LinkedIn: {linkedin}
GitHub: {github}

SUMMARY:
{summary}

EXPERIENCE:
{experience}

SKILLS:
Core: {core_skills}
Proficient: {proficient_skills}
Familiar: {familiar_skills}

EDUCATION:
{education}

PROJECTS:
{projects}

Instructions:
- Write a 2-3 sentence summary tailored to this specific role
- List experience in reverse chronological order
- Emphasize bullets most relevant to the required skills
- Put the most relevant skills first in the skills section
- Keep it to one page worth of content
""".strip()


class ResumeGenerator:

    def __init__(self):
        self.client = Groq(api_key=settings.groq_api_key)
        self.model = settings.groq_model
        self.log = logger.bind(component="ResumeGenerator")
        self.profile = self._load_profile()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def generate_for_job(self, job: Job) -> str | None:
        """
        Generate a tailored resume for a job.
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
                temperature=0.3,
                max_tokens=1500,
            )

            resume_text = response.choices[0].message.content.strip()
            file_path = self._save_to_file(job, resume_text)
            self._save_to_db(job, file_path, prompt)

            self.log.info(
                "Resume generated",
                job_id=job.id,
                title=job.title,
                file_path=str(file_path),
            )
            return str(file_path)

        except Exception as e:
            self.log.error("Resume generation failed", job_id=job.id, error=str(e))
            return None

    # ── Private ───────────────────────────────────────────────────────────────

    def _build_prompt(self, job: Job) -> str:
        personal = self.profile.get("personal", {})
        parsed = job.description_parsed or {}
        skills = self.profile.get("skills", {})

        # Format experience
        experience_lines = []
        for exp in self.profile.get("experience", []):
            experience_lines.append(
                f"\n{exp['title']} | {exp['company']} | {exp['start']} - {exp['end']}"
            )
            for bullet in exp.get("bullets", []):
                experience_lines.append(f"  • {bullet}")

        # Format education
        education_lines = []
        for edu in self.profile.get("education", []):
            education_lines.append(
                f"{edu['degree']} | {edu['institution']} | {edu['graduation']}"
            )

        # Format projects
        project_lines = []
        for proj in self.profile.get("projects", []):
            tech = ", ".join(proj.get("tech", []))
            project_lines.append(f"  • {proj['name']}: {proj['description']} [{tech}]")

        return USER_PROMPT_TEMPLATE.format(
            company=job.company,
            title=job.title,
            required_skills=", ".join(parsed.get("required_skills", [])[:8]),
            job_summary=parsed.get("summary", job.title),
            name=personal.get("name", ""),
            email=personal.get("email", ""),
            phone=personal.get("phone", ""),
            location=personal.get("location", ""),
            linkedin=personal.get("linkedin", ""),
            github=personal.get("github", ""),
            summary=self.profile.get("summary", ""),
            experience="\n".join(experience_lines),
            core_skills=", ".join(skills.get("core", [])),
            proficient_skills=", ".join(skills.get("proficient", [])),
            familiar_skills=", ".join(skills.get("familiar", [])),
            education="\n".join(education_lines),
            projects="\n".join(project_lines),
        )

    def _save_to_file(self, job: Job, text: str) -> Path:
        safe_company = re.sub(r'[^\w\-]', '_', job.company)[:30]
        safe_title = re.sub(r'[^\w\-]', '_', job.title)[:30]
        filename = f"{job.id}_{safe_company}_{safe_title}_resume.txt"
        file_path = OUTPUT_DIR / filename

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(text)

        return file_path

    def _save_to_db(self, job: Job, file_path: Path, prompt: str) -> None:
        with get_db_session() as db:
            doc = GeneratedDocument(
                id=str(ULID()),
                job_id=job.id,
                document_type=DocumentType.RESUME,
                file_path=str(file_path),
                prompt_used=prompt,
                model_used=self.model,
                created_at=datetime.now(timezone.utc),
            )
            db.add(doc)

    def _load_profile(self) -> dict:
        with open(PROFILE_PATH, "r") as f:
            return yaml.safe_load(f)