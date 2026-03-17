"""
db/session.py

Database engine and session factory.

Two ways to get a session:
  - get_db()         FastAPI dependency (use in API routes)
  - get_db_session() context manager   (use in Celery tasks and scripts)
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings

settings = get_settings()

# ── Engine ────────────────────────────────────────────────────────────────────
# pool_pre_ping=True tests the connection before using it from the pool.
# This handles database restarts gracefully — stale connections get
# discarded and replaced rather than causing cryptic errors.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=(settings.env == "development"),  # logs SQL queries in dev only
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # keep objects usable after commit in Celery tasks
)


# ── FastAPI dependency ────────────────────────────────────────────────────────

def get_db() -> Generator[Session, None, None]:
    """
    Yields a session scoped to one HTTP request.

    Usage in a route:
        from fastapi import Depends
        from sqlalchemy.orm import Session
        from db.session import get_db

        @router.get("/jobs")
        def list_jobs(db: Session = Depends(get_db)):
            return db.query(Job).all()
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Context manager for Celery tasks and scripts ──────────────────────────────

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for use outside FastAPI.

    Usage in a Celery task or script:
        from db.session import get_db_session

        with get_db_session() as db:
            db.add(some_model)
            db.commit()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Dev utility ───────────────────────────────────────────────────────────────

def create_all_tables() -> None:
    """
    Creates all tables directly from the ORM models.
    Only used in development — in production use Alembic migrations.
    Called automatically on startup when ENV=development.
    """
    from db.models import Base  # noqa: F401
    Base.metadata.create_all(bind=engine)