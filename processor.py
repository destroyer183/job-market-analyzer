"""Skill-frequency analysis over stored job postings.

Descriptions are pulled through SQLAlchemy rather than ``pl.read_database``:
Polars' database reader needs ``connectorx`` or ``pyarrow``/``adbc``, and none
of those are installed (see CLAUDE.md). Rows are handed to Polars as plain
tuples instead. Skill detection itself is vectorised — one regex pass per
skill across the whole ``description`` column, not a Python loop over rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from database import session_scope
from models import JobPosting, SkillFrequency

_EMPTY_SCHEMA = {
    "skill": pl.String,
    "posting_count": pl.Int64,
    "percentage": pl.Float64,
    "mention_count": pl.Int64,
}


@dataclass(frozen=True)
class Skill:
    """A tracked technology and the regex that detects a mention of it."""

    name: str
    #: Rust-regex syntax (Polars' engine), case-insensitive via inline ``(?i)``.
    pattern: str


#: Word-boundary matches so "SQL" doesn't fire inside "MySQL", "React" doesn't
#: fire inside "Reactor", etc. Extend freely — nothing else needs to change.
TARGET_SKILLS: tuple[Skill, ...] = (
    Skill("Python", r"(?i)\bpython\b"),
    Skill("TypeScript", r"(?i)\btypescript\b"),
    Skill("JavaScript", r"(?i)\bjavascript\b"),
    Skill("FastAPI", r"(?i)\bfastapi\b"),
    Skill("React", r"(?i)\breact\b"),
    Skill("SQL", r"(?i)\bsql\b"),
    Skill("PostgreSQL", r"(?i)\bpostgres(?:ql)?\b"),
    Skill("Docker", r"(?i)\bdocker\b"),
    Skill("AWS", r"(?i)\baws\b"),
    Skill("Git", r"(?i)\bgit\b"),
)


def _load_descriptions() -> pl.DataFrame:
    """Non-null job descriptions as a two-column ``(id, description)`` frame."""
    with session_scope() as session:
        rows = (
            session.query(JobPosting.id, JobPosting.raw_description)
            .filter(JobPosting.raw_description.isnot(None))
            .all()
        )
    return pl.DataFrame(
        [tuple(row) for row in rows],
        schema=["id", "description"],
        orient="row",
    )


def compute_skill_frequencies(skills: Sequence[Skill] = TARGET_SKILLS) -> pl.DataFrame:
    """Posting- and mention-counts per tracked skill, most-mentioned first.

    ``posting_count`` is how many distinct postings mention the skill at least
    once; ``mention_count`` is the total number of occurrences, which can be
    higher if a description repeats a skill. ``percentage`` is posting_count
    over the number of postings that have a description at all.

    Returns a correctly-shaped empty DataFrame (not an error) when there are no
    descriptions to scan or no skills to look for.
    """
    frame = _load_descriptions()
    total_jobs = frame.height

    if total_jobs == 0 or not skills:
        return pl.DataFrame(schema=_EMPTY_SCHEMA)

    description = frame["description"]
    counts = []
    for skill in skills:
        matches_per_row = description.str.count_matches(skill.pattern)
        counts.append(
            {
                "skill": skill.name,
                "posting_count": int((matches_per_row > 0).sum()),
                "mention_count": int(matches_per_row.sum()),
            }
        )

    return (
        pl.DataFrame(counts)
        .with_columns((pl.col("posting_count") / total_jobs * 100).round(1).alias("percentage"))
        .select("skill", "posting_count", "percentage", "mention_count")
        .sort("posting_count", descending=True)
    )


def get_top_skills(limit: int = 10) -> list[SkillFrequency]:
    """The ``limit`` most-mentioned tracked skills, ready for an API response."""
    frame = compute_skill_frequencies().head(limit)
    return [SkillFrequency(**row) for row in frame.to_dicts()]


if __name__ == "__main__":
    for skill in get_top_skills():
        print(f"{skill.skill:12} {skill.posting_count:3} postings ({skill.percentage:5.1f}%) "
              f"{skill.mention_count:3} mentions")
