# ─── CAO 48.1 Compliance API ─────────────────────────────────────────
# Multi-stage build for a lean production image.
#
# Build:  docker build -t cao481-api .
# Run:    docker run -p 8000:8000 --env-file .env cao481-api

FROM --platform=linux/amd64 python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ─── Dependencies ──────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── Application code ─────────────────────────────────────────────────
COPY app/ ./app/

# ─── Runtime ───────────────────────────────────────────────────────────
EXPOSE 8000

# Health check for container orchestration (Docker, ECS, etc.)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/cao481/health')" || exit 1

# Run with uvicorn — production settings
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
