FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Deps système minimales (psycopg2 nécessite libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install deps en premier pour tirer parti du cache Docker
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && \
    pip install -e ".[dev]"

# Code source
COPY alembic.ini ./
COPY migrations ./migrations

EXPOSE 8200

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8200/api/v1/health || exit 1

CMD ["uvicorn", "tik_core.main:app", "--host", "0.0.0.0", "--port", "8200", "--proxy-headers"]
