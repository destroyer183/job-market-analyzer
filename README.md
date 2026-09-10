# Job Market Analyzer

A full-stack app that scrapes job postings, stores them in SQLite, scans the
descriptions for a tracked list of tech skills, and serves the results
through a FastAPI JSON API to a small TypeScript dashboard — job listings
with a company filter, and a ranked skill-frequency chart with a table-view
twin.

**Live demo:** https://job-market-analyzer-ny03.onrender.com/static/index.html

> The demo runs on Render's free tier, which spins down after inactivity —
> the first load after a quiet period can take 30–60 seconds while it wakes
> back up and re-scrapes.

## What it does

- **Scrapes** job postings asynchronously (`httpx` + `BeautifulSoup`) and
  persists them to SQLite, deduplicated by URL.
- **Analyses** every stored description with Polars, running a vectorised
  regex pass per tracked skill (Python, TypeScript, JavaScript, FastAPI,
  React, SQL, PostgreSQL, Docker, AWS, Git) to compute how many postings
  mention each one.
- **Serves** both the raw listings and the computed skill frequencies as a
  typed JSON API.
- **Displays** them on a dashboard: a filterable job table, a KPI row, and a
  skill-frequency bar chart with an accessible table-view alternative — the
  chart/table toggle and the "show more" row limiting are pure CSS, no
  JavaScript involved.

## Tech stack

| Layer      | Choice                         |
| ---------- | ------------------------------ |
| API        | FastAPI + Uvicorn               |
| Validation | Pydantic v2                     |
| ORM        | SQLAlchemy 2.0                  |
| Database   | SQLite (WAL mode)                |
| Scraping   | HTTPX (async) + BeautifulSoup4  |
| Analysis   | Polars                          |
| Frontend   | TypeScript + plain HTML/CSS — no framework, no bundler |
| Deployment | Docker (multi-stage build), Render |

Python 3.11. See `requirements.txt` for pinned versions.

## How it works

```
scraper.py  --parses-->  SQLite (jobs.db)  --reads-->  processor.py (Polars)
                                |                              |
                                +-----------> main.py (FastAPI) <----------+
                                                    |
                                          static/ (TS dashboard)
```

`scraper.py` and `main.py` never talk to each other directly — they're
connected only through the database, so either can be re-run or restarted
independently.

## Project structure

- `database.py` — SQLAlchemy engine, session factory, `init_db()`
- `models.py` — the `JobPosting` table + Pydantic schemas (`JobPostingCreate`,
  `JobPostingRead`, `SkillFrequency`)
- `scraper.py` — async fetch → parse → persist pipeline (defaults to a bundled
  mock fixture — see below)
- `processor.py` — the Polars skill-frequency analysis
- `main.py` — the FastAPI app and routes
- `static/` — `index.html`, `styles.css`, and `app.ts` (compiled to `app.js`)
- `Dockerfile` — multi-stage build (Node stage compiles the frontend, Python
  stage runs the app)

## Running it

### With Docker

```bash
docker build -t job-market-analyzer .
docker run -p 8000:8000 job-market-analyzer
```

Then open `http://localhost:8000/static/index.html`.

### Without Docker

```bash
pip install -r requirements.txt
python scraper.py            # populates jobs.db from the mock source
uvicorn main:app --reload
```

The frontend's TypeScript needs compiling once (and again after any edit to
`static/app.ts`):

```bash
cd static
npm ci
npx tsc          # or `npx tsc --watch` while working on it
```

## API

Interactive docs are auto-generated at `/docs`. The routes themselves:

| Method | Path              | Notes                                             |
| ------ | ----------------- | -------------------------------------------------- |
| GET    | `/api/health`      | Liveness check                                     |
| GET    | `/api/jobs`        | Paginated (`limit`, `offset`); optional `company` filter, case-insensitive |
| GET    | `/api/skills/top`  | Skill frequencies, most-mentioned first (`limit`)  |

## A note on the scraper

The default target is a **bundled mock fixture**, not a live site — this is
intentional, not a placeholder waiting to be swapped out carelessly. Most
major job boards prohibit scraping in their terms of service and block it
aggressively. Before ever pointing this at a real source: check that site's
ToS and `robots.txt`, prefer an official API where one exists, and keep the
existing rate limiting and `User-Agent` in place.

## Deployment notes

Containerized with a two-stage `Dockerfile` (a Node stage compiles the
TypeScript frontend; the final image only carries the compiled output, not
the Node toolchain). Deployed on Render's free tier, which has no persistent
disk — the container re-runs the scraper on every boot to repopulate
`jobs.db` from scratch, rather than relying on data surviving a restart.
