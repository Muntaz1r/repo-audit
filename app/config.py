import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Database configuration: defaults to SQLite for immediate zero-config testing if Postgres is not specified
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./repo_audit.db")

# Convert postgres:// to postgresql:// for SQLAlchemy compatibility if needed
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
PORT = int(os.getenv("PORT", "8000"))
MAX_REPO_SIZE_MB = int(os.getenv("MAX_REPO_SIZE_MB", "100"))
AUDIT_TIMEOUT_SECONDS = int(os.getenv("AUDIT_TIMEOUT_SECONDS", "60"))

# Base temp directory for sandboxed shallow clones
CUSTOM_WORKSPACE = os.getenv("WORKSPACE_DIR")
if CUSTOM_WORKSPACE:
    WORKSPACE_DIR = Path(CUSTOM_WORKSPACE)
else:
    WORKSPACE_DIR = Path(tempfile.gettempdir()) / "repo_audit_workspace"

WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
