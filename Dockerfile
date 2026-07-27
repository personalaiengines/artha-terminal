# ============================================
# ARTHA Terminal - API Image (Starlette JSON API)
# ============================================
# Serves the Next.js web UI (services/engines/DB). The Streamlit app has been
# retired — see archive/streamlit-legacy/.
# Build: docker compose build api

# --------------------------------------------
# Builder Stage
# --------------------------------------------
FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# --------------------------------------------
# Production Stage
# --------------------------------------------
FROM python:3.12-slim AS production
LABEL maintainer="ARTHA Terminal"
LABEL description="AI Equities Intelligence — JSON API"
WORKDIR /app

RUN groupadd -r artha && useradd -r -g artha -d /app -s /sbin/nologin artha
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN mkdir -p /data/db /data/logs /data/cache && chown -R artha:artha /app /data

# Backend the API depends on (no Streamlit UI).
COPY --chown=artha:artha config.py .
COPY --chown=artha:artha db/ ./db/
COPY --chown=artha:artha ingestion/ ./ingestion/
COPY --chown=artha:artha engines/ ./engines/
COPY --chown=artha:artha agent/ ./agent/
COPY --chown=artha:artha services/ ./services/
COPY --chown=artha:artha api/ ./api/
COPY --chown=artha:artha scripts/ ./scripts/

ENV ARTHA_DB_PATH=/data/db/artha.db \
    ARTHA_DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER artha
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
