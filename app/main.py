
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.security_middleware import (
    SecurityHeadersMiddleware,
    LoginRateLimitMiddleware,
)
from app.database import SessionLocal
from app.routers import (
    auth,
    users,
    jobs,
    applications,
    interviews,
)
from app.web import router as web_router


BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Alembic manages database migrations.
    yield


app = FastAPI(
    title="Enterprise Recruitment ATS",
    description=(
        "Recruitment and Applicant Tracking System "
        "using FastAPI, SQLAlchemy and MySQL."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ==========================================
# BROWSER SESSION
# ==========================================

# Reuse the configured JWT secret for development.
# For deployment, use a dedicated SESSION_SECRET_KEY.
from app.config import Settings

config = Settings()

session_secret = os.getenv(
    "SESSION_SECRET_KEY"
) or config.JWT_SECRET_KEY

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    session_cookie="ats_session",
    max_age=3600,
    same_site="lax",
    https_only=os.getenv(
        "SESSION_HTTPS_ONLY", "false"
    ).lower() == "true",
)

# Phase 8: Security middleware
app.add_middleware(
    SecurityHeadersMiddleware
)

app.add_middleware(
    LoginRateLimitMiddleware,
    max_attempts=5,
    window_seconds=60,
)
# ==========================================
# STATIC FILES
# ==========================================

app.mount(
    "/static",
    StaticFiles(
        directory=str(BASE_DIR / "static")
    ),
    name="static",
)


# ==========================================
# API ROUTERS
# ==========================================

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(jobs.router)
app.include_router(applications.router)
app.include_router(interviews.router)


# ==========================================
# WEB ROUTER
# ==========================================

app.include_router(web_router)


@app.get("/")
def root():
    return {
        "message": "Enterprise Recruitment ATS API",
        "dashboard": "/login",
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected",
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )
from app.phase7_models import CandidateProfile, Resume, JobRequirement
from app.routers.phase7 import router as phase7_router

app.include_router(phase7_router)