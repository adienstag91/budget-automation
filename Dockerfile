# Single-container build: compile the React frontend, then run the FastAPI
# backend (api.py) which serves both /api and the built SPA from one origin.

# ---- Stage 1: build the React/Vite frontend ----
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # outputs to frontend/dist

# ---- Stage 2: Python API serving the built frontend ----
FROM python:3.12-slim AS app
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements_api.txt ./
RUN pip install --no-cache-dir -r requirements_api.txt

# Application code (uvicorn runs from /app, so `import budget_automation` and
# `import api` both resolve without installing the package).
COPY api.py ./
COPY budget_automation ./budget_automation
COPY scripts ./scripts
COPY data ./data

# Built SPA from stage 1 — api.py serves it when frontend/dist exists.
COPY --from=frontend /app/frontend/dist ./frontend/dist

EXPOSE 8000
# Bind to $PORT when the platform provides one (Railway/Render), else 8000
# (local docker run, Fly). Shell form so the variable expands.
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
