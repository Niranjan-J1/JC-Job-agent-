"""
db/models.py

All SQLAlchemy ORM models. Each class maps to one database table.

Tables:
  - Job               one row per scraped job posting
  - Application       one row per application attempt
  - GeneratedDocument tracks every resume / cover letter file produced
  - PipelineRun       audit log of each nightly pipeline execution
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ─────────────────────────────────────────────────────────────────────
# Stored as strings in the DB so they're readable in raw SQL.

class JobStatus(str, enum.Enum):
    NEW = "new"               # just scraped, not yet scored
    SCORED = "scored"         # scoring done, waiting to apply
    APPLYING = "applying"     # bot is currently running
    APPLIED = "applied"       # successfully submitted
    QUEUED = "queued"         # sitting in manual/assisted queue
    SKIPPED = "skipped"       # below score threshold
    FAILED = "failed"         # application attempt failed


class ApplicationStatus(str, enum.Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    INTERVIEWING = "interviewing"
    REJECTED = "rejected"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"


class AutomationTier(str, enum.Enum):
    TIER1 = "tier1"   # full automation (Workday, Greenhouse, Lever, EasyApply)
    TIER2 = "tier2"   # assisted: bot fills form, human submits
    TIER3 = "tier3"   # manual: human does everything


class DocumentType(str, enum.Enum):
    RESUME = "resume"
    COVER_LETTER = "cover_letter"


class PipelineRunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"       # completed but with some errors


# ── Base ──────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Models ────────────────────────────────────────────────────────────────────

class Job(Base):
    """
    One row per unique job posting.
    url is unique — used to deduplicate across scraper runs.
    description_parsed holds the LLM parser output as JSONB so we
    can query inside it directly in Postgres if needed.
    """
    __tablename__ = "jobs"

    id = Column(String(26), primary_key=True)          # ULID
    source = Column(String(64), nullable=False)         # "linkedin", "indeed", etc.
    company = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    url = Column(Text, nullable=False, unique=True)
    location = Column(String(255))
    employment_type = Column(String(64))
    description_raw = Column(Text)                      # raw scraped text
    description_parsed = Column(JSONB)                  # structured output from parser
    match_score = Column(Float)                         # 0.0 to 1.0
    match_reasons = Column(JSONB)                       # {"matched_skills": [], "penalties": []}
    automation_tier = Column(Enum(AutomationTier))
    status = Column(
        Enum(JobStatus),
        nullable=False,
        default=JobStatus.NEW,
    )
    scraped_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    scored_at = Column(DateTime(timezone=True))

    # Relationships — lets you do job.application and job.documents in Python
    application = relationship(
        "Application",
        back_populates="job",
        uselist=False,           # one-to-one: a job has at most one application
    )
    documents = relationship(
        "GeneratedDocument",
        back_populates="job",
    )


class Application(Base):
    """
    One row per application attempt.
    Tracks the full lifecycle from pending through to offer or rejection.
    resume_path and cover_letter_path point to files in /app/output/.
    """
    __tablename__ = "applications"

    id = Column(String(26), primary_key=True)
    job_id = Column(
        String(26),
        ForeignKey("jobs.id"),
        nullable=False,
        index=True,
    )
    status = Column(
        Enum(ApplicationStatus),
        nullable=False,
        default=ApplicationStatus.PENDING,
    )
    automation_tier = Column(Enum(AutomationTier), nullable=False)
    resume_path = Column(Text)
    cover_letter_path = Column(Text)
    notes = Column(Text)                                # bot error details or human notes
    applied_at = Column(DateTime(timezone=True))        # set when status → SUBMITTED
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    job = relationship("Job", back_populates="application")


class GeneratedDocument(Base):
    """
    Tracks every resume and cover letter the system generates.
    Keeping this separate from Application means we can regenerate
    documents without affecting the application record.
    prompt_used is stored for debugging — lets you see exactly what
    the LLM was given when a document came out wrong.
    """
    __tablename__ = "generated_documents"

    id = Column(String(26), primary_key=True)
    job_id = Column(
        String(26),
        ForeignKey("jobs.id"),
        nullable=False,
        index=True,
    )
    document_type = Column(Enum(DocumentType), nullable=False)
    file_path = Column(Text, nullable=False)
    prompt_used = Column(Text)
    model_used = Column(String(64))
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )

    job = relationship("Job", back_populates="documents")


class PipelineRun(Base):
    """
    One row per nightly pipeline execution.
    The dashboard's run history table reads from this.
    error_log stores a plain text description of any failures.
    """
    __tablename__ = "pipeline_runs"

    id = Column(String(26), primary_key=True)
    status = Column(
        Enum(PipelineRunStatus),
        nullable=False,
        default=PipelineRunStatus.RUNNING,
    )
    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    ended_at = Column(DateTime(timezone=True))

    # Counters — populated at the end of each run
    jobs_scraped = Column(Integer, default=0)
    jobs_new = Column(Integer, default=0)
    jobs_scored = Column(Integer, default=0)
    applied_tier1 = Column(Integer, default=0)
    queued_tier2 = Column(Integer, default=0)
    queued_tier3 = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    failed = Column(Integer, default=0)

    error_log = Column(Text)