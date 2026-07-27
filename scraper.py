"""Async job-posting scraper: fetch → parse → persist.

The three stages are separate functions so each is testable on its own:

* :func:`fetch_html`   — network only (async, retried, rate-limited)
* :func:`parse_jobs`   — pure: HTML string in, validated schemas out
* :func:`save_jobs`    — persistence only (sync, deduped on ``url``)

The default source is a **local fixture**, not a live site, so
``python scraper.py`` works offline and in CI. The fixture is real HTML in the
same shape as a live page, so the parser is genuinely exercised rather than
bypassed. See CLAUDE.md before repointing this at a real target.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from database import init_db, session_scope
from models import JobPosting, JobPostingCreate

logger = logging.getLogger(__name__)

USER_AGENT = "job-market-analyzer/0.1 (personal portfolio project)"
REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MAX_CONCURRENCY = 4
DELAY_BETWEEN_REQUESTS = 1.0
MAX_RETRIES = 3

#: ``lxml`` is not installed — see CLAUDE.md.
HTML_PARSER = "html.parser"

# A coroutine that turns a URL into an HTML string. Swap it out in tests.
Fetcher = Callable[[str], Awaitable[str]]


@dataclass(frozen=True)
class JobSource:
    """A scrape target and the CSS selectors needed to read it."""

    name: str
    url: str
    card_selector: str
    title_selector: str
    company_selector: str
    location_selector: str
    description_selector: str
    date_selector: str


MOCK_SOURCE = JobSource(
    name="mock-board",
    url="https://example.invalid/jobs",
    card_selector="div.job-card",
    title_selector="h2.job-title",
    company_selector="span.company",
    location_selector="span.location",
    description_selector="div.description",
    date_selector="time.posted",
)

MOCK_HTML = """
<html><body>
  <div class="job-listings">
    <div class="job-card">
      <h2 class="job-title">Junior Data Engineer</h2>
      <span class="company">Acme Analytics</span>
      <span class="location">Manchester, UK</span>
      <div class="description">Build ETL pipelines in Python. SQL and Airflow experience welcome.</div>
      <time class="posted" datetime="2026-07-20T09:00:00">20 July 2026</time>
      <a class="apply" href="/jobs/junior-data-engineer-1">Apply</a>
    </div>
    <div class="job-card">
      <h2 class="job-title">Backend Developer (Python)</h2>
      <span class="company">Northwind Software</span>
      <span class="location">Remote</span>
      <div class="description">FastAPI and PostgreSQL. You will own service design end to end.</div>
      <time class="posted" datetime="2026-07-22T14:30:00">22 July 2026</time>
      <a class="apply" href="/jobs/backend-developer-python-2">Apply</a>
    </div>
    <div class="job-card">
      <h2 class="job-title">Data Analyst</h2>
      <span class="company">Bright Retail</span>
      <span class="location">Leeds, UK</span>
      <div class="description">Dashboards and reporting. Strong SQL required, Polars a plus.</div>
      <time class="posted" datetime="">Recently</time>
      <a class="apply" href="/jobs/data-analyst-3">Apply</a>
    </div>
    <!-- Malformed on purpose: no title, no link. parse_jobs must skip it. -->
    <div class="job-card">
      <span class="company">Ghost Corp</span>
    </div>
  </div>
</body></html>
"""


def _select_text(card: Tag, selector: str) -> str | None:
    """Text of the first match for ``selector``, or ``None`` if absent."""
    element = card.select_one(selector)
    if element is None:
        return None
    text = element.get_text(strip=True)
    return text or None


def _parse_datetime(card: Tag, selector: str) -> datetime | None:
    """Read an ISO timestamp from a ``<time datetime="...">`` attribute.

    Returns ``None`` for a missing, empty, or unparseable value — a bad date is
    not a reason to drop an otherwise good posting.
    """
    element = card.select_one(selector)
    if element is None:
        return None
    raw = element.get("datetime")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.strip())
    except ValueError:
        logger.debug("Unparseable date_posted: %r", raw)
        return None


def parse_jobs(html: str, source: JobSource) -> list[JobPostingCreate]:
    """Parse an HTML page into validated postings.

    Pure and synchronous — no network, no database. Cards that fail validation
    (missing title, company, or link) are logged and skipped rather than
    aborting the whole page.
    """
    soup = BeautifulSoup(html, HTML_PARSER)
    postings: list[JobPostingCreate] = []

    for index, card in enumerate(soup.select(source.card_selector)):
        link = card.select_one("a[href]")
        href = link.get("href") if link is not None else None
        if not isinstance(href, str) or not href.strip():
            logger.warning("[%s] card %d has no link; skipping", source.name, index)
            continue

        try:
            posting = JobPostingCreate(
                title=_select_text(card, source.title_selector),
                company=_select_text(card, source.company_selector),
                location=_select_text(card, source.location_selector),
                raw_description=_select_text(card, source.description_selector),
                date_posted=_parse_datetime(card, source.date_selector),
                url=urljoin(source.url, href.strip()),
            )
        except ValidationError as exc:
            logger.warning(
                "[%s] card %d failed validation; skipping (%s)",
                source.name,
                index,
                exc.errors()[0].get("msg", "unknown error"),
            )
            continue

        postings.append(posting)

    logger.info("[%s] parsed %d posting(s)", source.name, len(postings))
    return postings


async def fetch_html(
    client: httpx.AsyncClient,
    url: str,
    *,
    semaphore: asyncio.Semaphore | None = None,
) -> str:
    """GET ``url`` and return the body, retrying transient failures.

    Retries on network errors and 5xx/429 with exponential backoff. A 4xx other
    than 429 is a client mistake and raises immediately.
    """
    limiter = semaphore or asyncio.Semaphore(MAX_CONCURRENCY)

    async with limiter:
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code < 500
                    and exc.response.status_code != 429
                ):
                    raise
                last_error = exc
                if attempt < MAX_RETRIES:
                    backoff = DELAY_BETWEEN_REQUESTS * (2 ** (attempt - 1))
                    logger.warning(
                        "Fetch failed (attempt %d/%d) for %s: %s — retrying in %.1fs",
                        attempt,
                        MAX_RETRIES,
                        url,
                        exc,
                        backoff,
                    )
                    await asyncio.sleep(backoff)

        assert last_error is not None
        raise last_error


async def mock_fetcher(url: str) -> str:
    """Stand-in for :func:`fetch_html` that returns the bundled fixture."""
    await asyncio.sleep(0)  # yield control, mimicking real I/O
    logger.info("Using mock fixture for %s", url)
    return MOCK_HTML


def make_http_fetcher(client: httpx.AsyncClient) -> Fetcher:
    """Adapt a live client into the :data:`Fetcher` signature."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def _fetch(url: str) -> str:
        html = await fetch_html(client, url, semaphore=semaphore)
        await asyncio.sleep(DELAY_BETWEEN_REQUESTS)  # be polite
        return html

    return _fetch


def save_jobs(postings: Sequence[JobPostingCreate]) -> tuple[int, int]:
    """Insert postings, skipping any whose ``url`` is already stored.

    Synchronous by design — call it from async code via ``asyncio.to_thread``.
    Returns ``(inserted, skipped)``.
    """
    if not postings:
        return (0, 0)

    # Deduplicate within the batch first; the same posting can appear twice on
    # one page, and that would trip the UNIQUE constraint mid-flush.
    unique: dict[str, JobPostingCreate] = {str(p.url): p for p in postings}

    with session_scope() as session:
        existing: set[str] = {
            row[0]
            for row in session.query(JobPosting.url)
            .filter(JobPosting.url.in_(list(unique)))
            .all()
        }
        fresh = [p for url, p in unique.items() if url not in existing]
        session.add_all([JobPosting(**p.to_orm_kwargs()) for p in fresh])

    skipped = len(postings) - len(fresh)
    logger.info("Saved %d new posting(s), skipped %d duplicate(s)", len(fresh), skipped)
    return (len(fresh), skipped)


async def scrape_source(source: JobSource, fetcher: Fetcher) -> list[JobPostingCreate]:
    """Fetch and parse a single source."""
    html = await fetcher(source.url)
    return parse_jobs(html, source)


async def run_scrape(
    sources: Sequence[JobSource],
    fetcher: Fetcher | None = None,
) -> tuple[int, int]:
    """Scrape every source concurrently and persist the results.

    Defaults to the mock fetcher. Pass ``make_http_fetcher(client)`` for live
    requests. Returns ``(inserted, skipped)``.
    """
    active_fetcher: Fetcher = fetcher or mock_fetcher

    results = await asyncio.gather(
        *(scrape_source(source, active_fetcher) for source in sources),
        return_exceptions=True,
    )

    postings: list[JobPostingCreate] = []
    for source, result in zip(sources, results):
        if isinstance(result, BaseException):
            logger.error("[%s] scrape failed: %s", source.name, result)
            continue
        postings.extend(result)

    # save_jobs is blocking; keep it off the event loop.
    return await asyncio.to_thread(save_jobs, postings)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )
    init_db()
    inserted, skipped = await run_scrape([MOCK_SOURCE])
    print(f"Done. {inserted} inserted, {skipped} skipped.")


if __name__ == "__main__":
    asyncio.run(main())
