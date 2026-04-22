import os
import warnings
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

if SECRET_KEY == "dev-secret-key-change-in-production":
    warnings.warn(
        "SECRET_KEY is using the default value! "
        "Set a strong SECRET_KEY in .env for production.",
        stacklevel=1,
    )

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wensai.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")

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
