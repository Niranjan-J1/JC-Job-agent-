#Decides whatg jobs are worth applying for and how to apply to them 

"""
scoring/scorer.py

Scores parsed job descriptions against your resume profile.
Produces a match score from 0.0 to 1.0 and assigns a tier.

Scoring breakdown:
  - 60% skill match (weighted by core/proficient/familiar)
  - 20% role type match
  - 20% preference filters (location, employment type, seniority)
"""

import yaml
import structlog
from datetime import datetime, timezone
from pathlib import Path

from db.models import AutomationTier, Job, JobStatus
from db.session import get_db_session
from config.settings import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

PROFILE_PATH = Path("/app/config/resume_profile.yaml")

# Skill tier weights — core skills matter most
SKILL_WEIGHTS = {
    "core": 1.0,
    "proficient": 0.6,
    "familiar": 0.3,
}


class JobScorer:

    def __init__(self):
        self.log = logger.bind(component="JobScorer")
        self.profile = self._load_profile()

        # Build flat skill lookup: skill_name → weight
        self.skill_map: dict[str, float] = {}
        for tier, weight in SKILL_WEIGHTS.items():
            for skill in self.profile.get("skills", {}).get(tier, []):
                self.skill_map[skill.lower()] = weight

        self.preferences = self.profile.get("preferences", {})
        self.target_roles = [r.lower() for r in self.preferences.get("target_roles", [])]
        self.excluded_roles = [r.lower() for r in self.preferences.get("excluded_roles", [])]
        self.location_prefs = [l.lower() for l in self.preferences.get("location_preferences", [])]
        self.excluded_locations = [l.lower() for l in self.preferences.get("excluded_locations", [])]
        self.employment_types = [e.lower() for e in self.preferences.get("employment_types", [])]

    def score_job(self, job: Job) -> tuple[float, dict]:
        """
        Score a single job against the resume profile.

        Returns:
            (score, reasons) where score is 0.0-1.0 and reasons
            is a dict explaining the score breakdown.
        """
        if not job.description_parsed:
            self.log.warning("Job has no parsed description", job_id=job.id)
            return 0.0, {"error": "no parsed description"}

        parsed = job.description_parsed
        reasons = {
            "matched_skills": [],
            "missing_skills": [],
            "penalties": [],
            "bonuses": [],
            "breakdown": {},
        }

        # ── 1. Skill score (60%) ──────────────────────────────────────────────
        skill_score = self._score_skills(parsed, reasons)

        # ── 2. Role type score (20%) ──────────────────────────────────────────
        role_score = self._score_role(parsed, reasons)

        # ── 3. Preference score (20%) ─────────────────────────────────────────
        pref_score = self._score_preferences(job, parsed, reasons)

        # ── Final weighted score ──────────────────────────────────────────────
        final_score = (skill_score * 0.60) + (role_score * 0.20) + (pref_score * 0.20)
        final_score = round(min(max(final_score, 0.0), 1.0), 3)

        reasons["breakdown"] = {
            "skill_score": round(skill_score, 3),
            "role_score": round(role_score, 3),
            "preference_score": round(pref_score, 3),
            "final_score": final_score,
        }

        self.log.info(
            "Job scored",
            job_id=job.id,
            title=job.title,
            score=final_score,
            matched_skills=len(reasons["matched_skills"]),
        )

        return final_score, reasons

    def score_unscored_jobs(self, limit: int = 100) -> tuple[int, int]:
        """
        Finds all parsed but unscored jobs and scores them.
        Called by the nightly pipeline after parsing.

        Returns:
            (scored_count, skipped_count)
        """
        scored = 0
        skipped = 0

        with get_db_session() as db:
            jobs = (
                db.query(Job)
                .filter(
                    Job.description_parsed.isnot(None),
                    Job.match_score.is_(None),
                )
                .limit(limit)
                .all()
            )

            self.log.info("Jobs to score", count=len(jobs))

            for job in jobs:
                score, reasons = self.score_job(job)

                job.match_score = score
                job.match_reasons = reasons
                job.automation_tier = self._assign_tier(score)
                job.status = JobStatus.SCORED
                job.scored_at = datetime.now(timezone.utc)
                scored += 1

        self.log.info("Scoring complete", scored=scored, skipped=skipped)
        return scored, skipped

    # ── Private scoring methods ───────────────────────────────────────────────

    def _score_skills(self, parsed: dict, reasons: dict) -> float:
        """
        Computes skill match score.
        Weighted average of matched skills against required + preferred.
        """
        required = [s.lower() for s in parsed.get("required_skills", [])]
        preferred = [s.lower() for s in parsed.get("preferred_skills", [])]
        tech_stack = [s.lower() for s in parsed.get("tech_stack", [])]

        # Combine all job skills, required weighted higher
        all_job_skills = set(required + tech_stack)
        preferred_set = set(preferred)

        if not all_job_skills:
            return 0.5  # No skills listed — neutral score

        total_weight = 0.0
        matched_weight = 0.0

        for skill in all_job_skills:
            # Required skills count more than preferred
            weight = 1.0 if skill in set(required) else 0.5

            if skill in preferred_set:
                weight *= 0.7  # preferred skills matter less

            total_weight += weight

            if skill in self.skill_map:
                matched_weight += weight * self.skill_map[skill]
                reasons["matched_skills"].append(skill)
            else:
                if skill in set(required):
                    reasons["missing_skills"].append(skill)

        if total_weight == 0:
            return 0.5

        return matched_weight / total_weight

    def _score_role(self, parsed: dict, reasons: dict) -> float:
        """Checks if the role type matches your target roles."""
        role_type = parsed.get("role_type", "").lower()
        seniority = parsed.get("seniority", "").lower()
        title_lower = ""

        # Check for excluded roles
        for excluded in self.excluded_roles:
            if excluded in role_type or excluded in title_lower:
                reasons["penalties"].append(f"excluded role type: {excluded}")
                return 0.0

        # Check for target role match
        for target in self.target_roles:
            target_words = target.lower().split()
            if any(word in role_type for word in target_words):
                reasons["bonuses"].append(f"role match: {target}")
                return 1.0

        # engineering/ml roles always match for software engineers
        if role_type in ["engineering", "ml_ai", "data"]:
            return 0.8

        return 0.4  # Unknown or non-matching role

    def _score_preferences(self, job: Job, parsed: dict, reasons: dict) -> float:
        """Checks location, employment type, and seniority preferences."""
        score = 1.0

        # Location check
        job_location = (job.location or "").lower()
        remote_type = parsed.get("remote_type", "").lower()

        if remote_type == "remote":
            reasons["bonuses"].append("remote position")
        elif self.excluded_locations:
            for excluded in self.excluded_locations:
                if excluded in job_location:
                    reasons["penalties"].append(f"excluded location: {excluded}")
                    score -= 0.4

        # Employment type check
        job_employment = parsed.get("employment_type", "").lower()
        if self.employment_types and job_employment:
            if job_employment not in self.employment_types:
                reasons["penalties"].append(f"employment type mismatch: {job_employment}")
                score -= 0.3

        return max(score, 0.0)

    def _assign_tier(self, score: float) -> AutomationTier:
        """Assigns automation tier based on score thresholds from settings."""
        if score >= settings.auto_apply_threshold:
            return AutomationTier.TIER1
        elif score >= settings.assisted_apply_threshold:
            return AutomationTier.TIER2
        else:
            return AutomationTier.TIER3

    def _load_profile(self) -> dict:
        """Loads the resume profile YAML."""
        with open(PROFILE_PATH, "r") as f:
            return yaml.safe_load(f)