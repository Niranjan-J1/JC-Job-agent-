##Creates the fast API instance, Adds CORS middleware so Next.Js fronttedn can talk to backendn 
#On startup development, automatically create all databases tables so you dont bneed to run 
#Registers the three routers - jobs, applications and pipeline 
#provides /health endpoint to confrim if the server is running


import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_settings
from db.session import create_all_tables

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Job Application Agent",
    description="Automated job hunting pipeline API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Starting Job Agent API", env=settings.env)
    if settings.env == "development":
        # Auto-create tables in dev so you can start without Alembic.
        # In production always use: alembic upgrade head
        create_all_tables()
        logger.info("Database tables ensured")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("Shutting down Job Agent API")


# ── Routers ───────────────────────────────────────────────────────────────────
# Imported here to avoid circular imports at module load time.

from api.routes import applications, jobs, pipeline  # noqa: E402

app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(applications.router, prefix="/api/applications", tags=["applications"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])

# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "ok", "env": settings.env}