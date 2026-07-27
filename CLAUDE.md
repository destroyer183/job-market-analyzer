# Job Market Analyzer

Full-stack project that scrapes job postings, stores them in SQLite, analyses them
with Polars, and serves the results through a FastAPI JSON API to a small
TypeScript frontend.

## Tech stack

| Layer      | Choice                          | Notes                                              |
| ---------- | ------------------------------- | -------------------------------------------------- |
| API        | FastAPI + Uvicorn               | Async endpoints, Pydantic response models           |
| Validation | Pydantic v2                     | `model_config = ConfigDict(from_attributes=True)`   |
| ORM        | SQLAlchemy 2.0                  | Typed `DeclarativeBase` / `Mapped[...]` style       |
| Database   | SQLite                          | Single file `jobs.db`, WAL mode                     |
| Scraping   | HTTPX (async) + BeautifulSoup4  | `lxml` not installed — parse with `html.parser`     |
| Analysis   | Polars                          | Reads out of SQLite, not pandas                     |
| Frontend   | TypeScript + HTML               | Plain `static/`, no framework or bundler            |

Python 3.11. Pinned versions live in `requirements.txt`.

## Layout

- `database.py` — engine, session factory, `Base`, `init_db()`
- `models.py` — `JobPosting` ORM table + Pydantic schemas
- `scraper.py` — async fetch → parse → persist pipeline
- `processor.py` — Polars analysis over stored postings
- `main.py` — FastAPI app and routes
- `static/` — `index.html` + `app.ts` frontend

## Conventions

- **Type-hint everything.** `from __future__ import annotations` at the top of
  each module so `X | None` works consistently.
- **Sync DB, async I/O.** `aiosqlite` is not installed, so the SQLAlchemy engine
  is synchronous. Async code calls into it via `asyncio.to_thread(...)` rather
  than blocking the event loop. Swap to `sqlalchemy.ext.asyncio` only if
  `aiosqlite` is added.
- **ORM vs schema separation.** `JobPosting` is the table. `JobPostingCreate`
  (scraper output) and `JobPostingRead` (API output) are the Pydantic contracts.
  Never return an ORM object straight out of a route.
- **`url` is the natural key.** It carries a `UNIQUE` constraint and dedupes
  repeat scrapes; `id` is a surrogate autoincrement key.
- Session lifecycle: `get_db()` for FastAPI dependency injection,
  `session_scope()` for scripts and tests.

## Scraping policy

The default target in `scraper.py` is a **local mock fixture**, not a live site.
Before pointing it at a real source: check that site's ToS and `robots.txt`,
prefer an official/public API where one exists, keep the concurrency limit and
inter-request delay in place, and send a real `User-Agent`. Major job boards
(Indeed, LinkedIn) prohibit scraping and block it aggressively — don't target
them.

## Running

```bash
python scraper.py            # populate jobs.db from the mock source
uvicorn main:app --reload    # serve the API
```

## Gotchas

- `requirements.txt` is a full-machine `pip freeze` (contains pygame, PySide6,
  yt-dlp). Treat it as untrusted for this project's real dependency set.
- `.env` is git-tracked from the initial commit. It is currently empty; the
  `.gitignore` entry stops future secrets being committed, but the file must be
  `git rm --cached`'d if it ever gains real values.
- SQLite `datetime` columns are naive on read-back. `date_posted` is stored as
  UTC; don't assume tzinfo survives the round-trip.
