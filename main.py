"""FastAPI application: serves stored job postings and skill analytics."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import PROJECT_ROOT, get_db, init_db
from models import JobPosting, JobPostingRead, SkillFrequency
from processor import get_top_skills


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Create tables on startup so a fresh clone works before any scrape runs."""
    init_db()
    yield


app = FastAPI(
    title="Job Market Analyzer",
    description="Scraped job postings and tech-skill frequency analytics.",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/jobs", response_model=list[JobPostingRead])
def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    company: str | None = Query(default=None, min_length=1),
    db: Session = Depends(get_db),
) -> list[JobPosting]:
    """Paginated job postings, most recently scraped first.

    ``company`` does a case-insensitive substring match when given.
    """
    stmt = select(JobPosting).order_by(JobPosting.scraped_at.desc())
    if company:
        stmt = stmt.where(JobPosting.company.ilike(f"%{company}%"))
    stmt = stmt.offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


@app.get("/api/skills/top", response_model=list[SkillFrequency])
def top_skills(limit: int = Query(default=10, ge=1, le=50)) -> list[SkillFrequency]:
    """Tracked tech skills ranked by how many stored postings mention them."""
    return get_top_skills(limit=limit)
