import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import CORS_ORIGINS
from app.limiter import limiter
from app.logging_config import setup_logging
from app.approvals import router as approvals
from app.auth import router as auth
from app.agent_profiles import router as agent_profiles
from app.files import router as task_files
from app.internal_api import router as internal
from app.papers import router as papers
from app.realtime import router as task_ws
from app.reviews import router as reviews
from app.database import SessionLocal
from app.tasks.dispatcher import redispatch_queued_tasks
from app.tasks import router as tasks
from app.workspaces import router as workspaces

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting Paper Review API")
    db = SessionLocal()
    try:
        redispatched = await redispatch_queued_tasks(db)
        if redispatched:
            logger.info("Re-dispatched queued tasks on startup: %s", redispatched)
    finally:
        db.close()
    yield
    logger.info("Shutting down Paper Review API")


app = FastAPI(
    title="Paper Review API",
    description="API for paper submission and peer review",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS - allow frontend dev server & Tauri desktop
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(papers.router)
app.include_router(reviews.router)
app.include_router(tasks.router)
app.include_router(workspaces.router)
app.include_router(approvals.router)
app.include_router(task_files.router)
app.include_router(agent_profiles.router)
app.include_router(internal.router)
app.include_router(task_ws.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    logger.info(
        "%s %s %d %.0fms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
