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

# pyfedwatch (ADR-029) — maths CME FedWatch pour les probas de taux Fed.
# Installé --no-deps VOLONTAIREMENT : sa dépendance épinglée pandas_datareader==0.10.0
# casse à l'import contre pandas>=2.2 (deprecate_kwarg), et matplotlib (plot, non
# utilisé) est lourd. On neutralise ces 2 imports au runtime via
# tik_core.aggregator._pyfedwatch_compat (stubs sys.modules — sûrs car ces 2 libs
# ne sont utilisées NULLE PART ailleurs dans Tik). On installe en revanche les
# vraies deps que `datareader.py` importe au niveau module (requests + bs4, légères
# et standard) pour que `import pyfedwatch` aboutisse. Le reste (pandas/numpy/
# python-dateutil/holidays) vient de pyproject.
RUN pip install --no-deps pyfedwatch==1.2.0 && pip install requests beautifulsoup4

# Code source
COPY alembic.ini ./
COPY migrations ./migrations

EXPOSE 8200

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8200/api/v1/health || exit 1

CMD ["uvicorn", "tik_core.main:app", "--host", "0.0.0.0", "--port", "8200", "--proxy-headers"]
