"""ORM table and Pydantic schemas for job postings.

Three types, deliberately kept separate:

* :class:`JobPosting`       — the SQLAlchemy table (persistence)
* :class:`JobPostingCreate` — validated scraper output (input contract)
* :class:`JobPostingRead`   — API response body (output contract)

Routes should return ``JobPostingRead``, never a bare ORM instance.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def _utcnow() -> datetime:
    """Timezone-aware UTC now (``datetime.utcnow`` is deprecated in 3.12+)."""
    return datetime.now(timezone.utc)


class JobPosting(Base):
    """A single scraped job posting.

    ``url`` is the natural key and carries a UNIQUE constraint, so re-running the
    scraper over the same source cannot create duplicate rows.
    """

    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nullable: boards often show a relative date ("3 days ago") or none at all.
    date_posted: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True, index=True)
    # Provenance — not scraped, set on insert. Makes stale rows debuggable.
    scraped_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_job_postings_company_title", "company", "title"),
        Index("ix_job_postings_date_posted", "date_posted"),
    )

    def __repr__(self) -> str:
        return f"<JobPosting id={self.id!r} title={self.title!r} company={self.company!r}>"


class JobPostingBase(BaseModel):
    """Fields common to the input and output schemas."""

    title: str = Field(..., min_length=1, max_length=255)
    company: str = Field(..., min_length=1, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    raw_description: str | None = None
    date_posted: datetime | None = None

    @field_validator("title", "company", "location", "raw_description", mode="before")
    @classmethod
    def _strip_whitespace(cls, value: object) -> object:
        """Collapse scraped whitespace; treat an empty result as missing."""
        if isinstance(value, str):
            cleaned = " ".join(value.split())
            return cleaned or None
        return value


class JobPostingCreate(JobPostingBase):
    """A posting parsed by the scraper, before it is persisted.

    ``url`` is validated as a real URL here — the strict boundary is the point of
    this schema. It is coerced back to ``str`` so SQLAlchemy can bind it.
    """

    url: HttpUrl

    def to_orm_kwargs(self) -> dict[str, object]:
        """Column keyword arguments for constructing a :class:`JobPosting`."""
        data = self.model_dump()
        data["url"] = str(self.url)
        return data


class JobPostingRead(JobPostingBase):
    """A posting as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    scraped_at: datetime


class SkillFrequency(BaseModel):
    """One tracked skill's mention frequency across stored postings.

    Produced by :func:`processor.get_top_skills`, not persisted anywhere.
    """

    skill: str
    #: Distinct postings mentioning the skill at least once.
    posting_count: int = Field(..., ge=0)
    #: posting_count as a percentage of postings that have a description.
    percentage: float = Field(..., ge=0, le=100)
    #: Total occurrences, which can exceed posting_count if a description
    #: repeats a skill.
    mention_count: int = Field(..., ge=0)
