"""Central configuration. Everything comes from environment variables so the
same code runs locally (SQLite fallback) and on Railway (Postgres)."""
import os


def _normalize_db_url(url: str) -> str:
    # Railway/Heroku legacy scheme
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL = _normalize_db_url(os.getenv("DATABASE_URL", "sqlite:///./revcadence.db"))

# Secret used to sign JWTs. MUST be set in production (Railway → Variables).
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-secret-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_HOURS = int(os.getenv("ACCESS_TOKEN_HOURS", "12"))

APP_NAME = "RevCadence"
VERSION = "0.1.0"

# Worker poll interval (seconds) for the job queue.
WORKER_POLL_SECONDS = int(os.getenv("WORKER_POLL_SECONDS", "5"))
