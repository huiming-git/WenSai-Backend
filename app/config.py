import os
import warnings
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "43200"))

if SECRET_KEY == "dev-secret-key-change-in-production":
    warnings.warn(
        "SECRET_KEY is using the default value! "
        "Set a strong SECRET_KEY in .env for production.",
        stacklevel=1,
    )

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wensai.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "120"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Shanghai")

# 自动 create_all 仅对单进程 SQLite 安全；Postgres + 多 worker 会并发建表撞唯一约束，只走 Alembic
INIT_DB_ON_STARTUP = _env_bool("INIT_DB_ON_STARTUP", DATABASE_URL.startswith("sqlite"))

# LLM Configuration (OpenAI-compatible)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")

# Invite code for registration
INVITE_CODE = os.getenv("INVITE_CODE", "huiming")

# Storage backend: "local" or "s3"
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")  # for MinIO / custom S3
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")
S3_REGION = os.getenv("S3_REGION", "us-east-1")

# CORS allowed origins (comma-separated in env)
_default_origins = "http://localhost:1420,http://127.0.0.1:1420,http://localhost:5173,http://127.0.0.1:5173"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",") if o.strip()]
