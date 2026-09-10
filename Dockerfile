# ---------- Stage 1: compile the TypeScript frontend ----------
# Only this stage needs Node -- its entire job is turning app.ts into
# app.js. Nothing else from here makes it into the final image; the whole
# node_modules tree this stage builds gets discarded along with it.
FROM node:20-slim AS frontend-build

WORKDIR /app

# Bring in the whole static/ directory: app.ts, tsconfig.json, package.json,
# package-lock.json, index.html, styles.css. app.js / app.js.map are
# excluded by .dockerignore, so a locally-compiled copy can never leak in
# here and mask a broken build.
COPY static ./static

# Everything below operates on the frontend project itself, not /app --
# package.json and tsconfig.json both live here, and tsc looks for its
# config in the current directory.
WORKDIR /app/static

# npm ci installs exactly what's locked, rather than potentially
# re-resolving versions -- the reproducibility a container is for.
RUN npm ci

# Compiles in place: app.ts -> app.js, right next to it, per tsconfig.json.
RUN npx tsc


# ---------- Stage 2: the actual application ----------
FROM python:3.11-slim

WORKDIR /app

# Manifest before source: this layer is only invalidated (forcing a pip
# reinstall) when requirements.txt itself changes, not on every code edit.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The rest of the real source: .py files, static/index.html, static/styles.css,
# etc. .dockerignore keeps jobs.db, __pycache__, node_modules, .git, and any
# compiled static/*.js out of this.
COPY . .

# Pull across only the two compiled files -- not the whole static/
# directory from the other stage, which would also drag its node_modules
# (and everything else already copied above) into this image.
# .dockerignore has no effect on a --from= copy, since that source isn't
# the local build context -- it's another stage's filesystem, so being
# this specific is what actually keeps Node's dependency tree out.
COPY --from=frontend-build /app/static/app.js /app/static/app.js.map ./static/

EXPOSE 8000

# No --reload (dev-only) and an explicit 0.0.0.0 -- uvicorn's default
# 127.0.0.1 only accepts connections from inside the container itself.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
