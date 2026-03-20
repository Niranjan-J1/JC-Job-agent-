#where all configuratuons values in the entire app is deifned 

# pydantic -settinsg reads .env file and maps each variable to a typed Python attribute 
#If a required variable is missing from .env teh app refues to start and tells you exactly whayts missing 


from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── App ───────────────────────────────────────────────────────────────
    env: str = "development"
    secret_key: str = "change-this-in-production"
    output_dir: str = "/app/output"

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str

    # ── Redis / Celery ────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # ── AI ────────────────────────────────────────────────────────────────
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    # ── Pipeline schedule ─────────────────────────────────────────────────
    pipeline_cron_hour: int = 2
    pipeline_cron_minute: int = 0

    # ── Scraper credentials ───────────────────────────────────────────────
    linkedin_email: str = ""
    linkedin_password: str = ""
    waterloo_works_username: str = ""
    waterloo_works_password: str = ""

    # ── Scoring thresholds ────────────────────────────────────────────────
    # Above auto_apply_threshold   → Tier 1 (fully automated)
    # Between the two thresholds   → Tier 2 (assisted)
    # Below assisted_threshold     → Tier 3 (manual queue)
    auto_apply_threshold: float = 0.75
    assisted_apply_threshold: float = 0.50

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached singleton Settings instance.
    Call this anywhere in the app — it reads .env once then caches.

    Usage:
        from config.settings import get_settings
        settings = get_settings()
        print(settings.database_url)
    """
    return Settings()