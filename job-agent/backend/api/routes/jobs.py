#Handles all the HTTP endpoints for job postings
#The dashboards main table and filter controls cal these 

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.models import AutomationTier, Job, JobStatus
from db.session import get_db

router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────────
# Pydantic models that define what the API returns.
# We never return the raw ORM object directly — always serialize through these.

class JobOut(BaseModel):
    id: str
    source: str
    company: str
    title: str
    url: str
    location: Optional[str]
    employment_type: Optional[str]
    match_score: Optional[float]
    automation_tier: Optional[str]
    status: str
    scraped_at: str

    model_config = {"from_attributes": True}


class JobDetailOut(JobOut):
    """Extended version with full description — used for the detail view."""
    description_raw: Optional[str]
    description_parsed: Optional[dict]
    match_reasons: Optional[dict]
    scored_at: Optional[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[JobOut])
def list_jobs(
    status: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    source: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Job)

    if status:
        try:
            q = q.filter(Job.status == JobStatus(status))
        except ValueError:
            raise HTTPException(400, detail=f"Invalid status: {status}")

    if tier:
        try:
            q = q.filter(Job.automation_tier == AutomationTier(tier))
        except ValueError:
            raise HTTPException(400, detail=f"Invalid tier: {tier}")

    if min_score is not None:
        q = q.filter(Job.match_score >= min_score)

    if source:
        q = q.filter(Job.source == source)

    return q.order_by(desc(Job.scraped_at)).offset(offset).limit(limit).all()


@router.get("/stats")
def job_stats(db: Session = Depends(get_db)):
    """Aggregate counts for the dashboard summary cards."""
    total = db.query(Job).count()
    by_status = {
        status.value: db.query(Job).filter(Job.status == status).count()
        for status in JobStatus
    }
    return {"total": total, "by_status": by_status}


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, detail="Job not found")
    return job


@router.patch("/{job_id}/status")
def update_job_status(
    job_id: str,
    new_status: str,
    db: Session = Depends(get_db),
):
    """Manual status override from the dashboard."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, detail="Job not found")

    try:
        job.status = JobStatus(new_status)
    except ValueError:
        raise HTTPException(400, detail=f"Invalid status: {new_status}")

    db.commit()
    return {"id": job_id, "status": job.status}

