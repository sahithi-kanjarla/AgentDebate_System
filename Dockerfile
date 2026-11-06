# Tribunal: one container serves the API and the built frontend (Render Docker web service, or
# Hugging Face Spaces, Docker SDK).
#
#   docker build -t tribunal .
#
# No secrets are baked in: API keys arrive as runtime environment variables (Space Secrets).

# ---- 1. frontend build ----------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# tsc + vite build; then fail if test fixtures leaked into the bundle.
RUN npm run build && node scripts/check-bundle.mjs

# ---- 2. python dependencies (uv stays in this stage) ------------------------------------------
FROM python:3.12-slim AS py
RUN pip install --no-cache-dir uv==0.11.26
WORKDIR /build
COPY backend/pyproject.toml backend/uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN uv sync --frozen --no-dev --no-install-project

# ---- 3. runtime -------------------------------------------------------------------------------
FROM python:3.12-slim
# Non-root; uid 1000 is also what Hugging Face Spaces expects.
RUN useradd --create-home --uid 1000 user
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY --from=py /opt/venv /opt/venv
WORKDIR /app
COPY --chown=user backend/app ./backend/app
COPY --chown=user backend/config ./backend/config
COPY --from=web --chown=user /web/dist ./frontend/dist
# The database and the response cache live here. Spaces storage is ephemeral: it is empty after
# every restart, rebuild or wake from sleep (see docs/DEPLOY.md).
RUN mkdir -p /home/user/data && chown user:user /home/user/data

# Production defaults. Space variables override them; keys come from Space Secrets only.
# PORT: Render injects it (10000 by default); Spaces and local runs use 7860.
ENV PORT=7860 \
    FRONTEND_DIST=/app/frontend/dist \
    DATABASE_URL=sqlite:////home/user/data/tribunal.db \
    AGENTS_CONFIG=/app/backend/config/agents.yaml \
    RATE_LIMIT_ENABLED=true \
    RATE_LIMIT_PER_HOUR=5 \
    RATE_LIMIT_PER_DAY=20 \
    GLOBAL_DAILY_CAP=15 \
    MAX_CONCURRENT_DEBATES=3 \
    TRUSTED_PROXY=1 \
    EXPOSE_AGENT_MODELS=false \
    CACHE_ENABLED=true \
    LOG_LEVEL=INFO

USER user
WORKDIR /app/backend
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '7860'), timeout=4)"
# One worker: rate-limit counters and live-debate streams are in process. Our own client-IP logic
# (TRUSTED_PROXY) decides which address counts, so uvicorn's proxy-header rewriting is off; the
# access log is off so visitor addresses and URLs are not written to the logs. The shell form
# lets ${PORT} expand; exec keeps uvicorn as PID 1 so it receives SIGTERM.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860} --no-proxy-headers --no-access-log"]
