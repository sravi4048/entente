import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        data_dir = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{data_dir / 'entente.db'}"
    # Heroku / Render / Fly hand out postgres:// URLs; SQLAlchemy wants postgresql+psycopg2://
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _database_url()

# Set COOKIE_SECURE=1 when serving over HTTPS (any real deployment).
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") in ("1", "true", "True")
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30"))

# How often the deadline scheduler wakes up.
SCHEDULER_INTERVAL_SECONDS = int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "15"))

# Built frontend (Vite output). In Docker this is copied to /app/static.
STATIC_DIR = Path(os.environ.get("STATIC_DIR", BASE_DIR.parent / "frontend" / "dist"))

# Shown in the UI footer. The game engine is AGPL-3.0, so a public deployment
# must offer users the source of the running app.
SOURCE_URL = os.environ.get("SOURCE_URL", "")

# Sign-up gate: if set, new accounts must enter this code. Share it with your friends.
SIGNUP_CODE = os.environ.get("SIGNUP_CODE", "").strip()

# Comma-separated usernames allowed to approve maps. If empty, the first account
# ever created is the admin.
ADMIN_USERNAMES = {u.strip().lower() for u in os.environ.get("ADMIN_USERNAMES", "").split(",") if u.strip()}

# Optional: lets reviewers turn a map's plain-text rules into adjacency changes.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

MAPS_CACHE_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data")) / "maps"
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "12")) * 1024 * 1024
