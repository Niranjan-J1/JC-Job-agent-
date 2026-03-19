#Ednpounts for triggerinig pipleone runs and viewing run history 
#the dasboards run now button and run history tabnle call these 

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.models import PipelineRun
from db.session import get_db

router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────────

class PipelineRunOut(BaseModel):
    id: str
    status: str
    started_at: str
    ended_at: Optional[str]
    jobs_scraped: Optional[int]
    jobs_new: Optional[int]
    jobs_scored: Optional[int]
    applied_tier1: Optional[int]
    queued_tier2: Optional[int]
    queued_tier3: Optional[int]
    skipped: Optional[int]
    failed: Optional[int]

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/runs", response_model=list[PipelineRunOut])
def list_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Returns the most recent pipeline runs, newest first."""
    return (
        db.query(PipelineRun)
        .order_by(desc(PipelineRun.started_at))
        .limit(limit)
        .all()
    )


@router.get("/runs/latest", response_model=PipelineRunOut)
def get_latest_run(db: Session = Depends(get_db)):
    """Returns the most recent pipeline run. Used by the dashboard header."""
    run = (
        db.query(PipelineRun)
        .order_by(desc(PipelineRun.started_at))
        .first()
    )
    if not run:
        raise HTTPException(404, detail="No pipeline runs yet")
    return run


@router.get("/runs/{run_id}", response_model=PipelineRunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
    if not run:
        raise HTTPException(404, detail="Run not found")
    return run


@router.post("/trigger")
def trigger_pipeline():
    """
    Manually triggers the pipeline via the dashboard.
    Enqueues a Celery task rather than running inline so the
    HTTP request returns immediately.
    """
    from pipeline.tasks import run_nightly_pipeline
    task = run_nightly_pipeline.delay()
    return {"task_id": task.id, "message": "Pipeline triggered"}


@router.get("/status/{task_id}")
def get_task_status(task_id: str):
    """
    Poll the status of a triggered pipeline task.
    The dashboard calls this after triggering to show progress.
    """
    from pipeline.tasks import celery_app
    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "state": result.state,
        "info": str(result.info) if result.info else None,
    }