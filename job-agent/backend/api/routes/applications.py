#Endpoiny for application records 
#The tier 2/3 review queue in the dahsboard 


from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.models import Application, ApplicationStatus
from db.session import get_db

router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────────

class ApplicationOut(BaseModel):
    id: str
    job_id: str
    status: str
    automation_tier: str
    resume_path: Optional[str]
    cover_letter_path: Optional[str]
    notes: Optional[str]
    applied_at: Optional[str]
    created_at: str

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[ApplicationOut])
def list_applications(
    status: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Application)

    if status:
        try:
            q = q.filter(Application.status == ApplicationStatus(status))
        except ValueError:
            raise HTTPException(400, detail=f"Invalid status: {status}")

    if tier:
        q = q.filter(Application.automation_tier == tier)

    return q.order_by(desc(Application.created_at)).offset(offset).limit(limit).all()


@router.get("/{application_id}", response_model=ApplicationOut)
def get_application(application_id: str, db: Session = Depends(get_db)):
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(404, detail="Application not found")
    return app


@router.patch("/{application_id}/status")
def update_application_status(
    application_id: str,
    new_status: str,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Update status from the dashboard.
    For example — mark a Tier 2 application as SUBMITTED after you
    manually submit it.
    """
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(404, detail="Application not found")

    try:
        app.status = ApplicationStatus(new_status)
    except ValueError:
        raise HTTPException(400, detail=f"Invalid status: {new_status}")

    if notes:
        app.notes = notes

    db.commit()
    return {"id": application_id, "status": app.status}