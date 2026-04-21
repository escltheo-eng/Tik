# Tik Core

Service FastAPI central du moteur Tik. Source de vérité unique.

---

## Responsabilités

- Agrégation OSINT multi-sources (marché, macro, news, on-chain…)
- Scoring de crédibilité par source
- Détection de fake news (cross-validation multi-sources)
- Triple scoring par entity : **flash** (minutes-heures), **swing** (jours-semaines), **macro** (semaines-mois)
- Historisation time-series (TimescaleDB)
- API REST + WebSocket pour les SDK clients

---

## Stack

- **Python 3.11** + **FastAPI** + **Uvicorn**
- **PostgreSQL 16** + **TimescaleDB** — historisation
- **Redis 7** — pub/sub + cache
- **SQLAlchemy 2** + **Alembic** — ORM et migrations
- **Pydantic v2** — validation
- **httpx** — clients HTTP async

---

## Démarrage local (Docker Compose)

### 1. Prérequis
- Docker Desktop installé
- Port libres : 8200 (API), 5432 (Postgres), 6379 (Redis)

### 2. Setup

```bash
cd core
cp .env.example .env
# Éditer .env et remplacer les valeurs XXX par des vraies
```

### 3. Lancement

```bash
docker compose up -d
# Attendre ~15s le démarrage complet

# Vérifier que tout est OK
curl http://localhost:8200/api/v1/health
# -> {"status":"ok","version":"0.1.0"}

# Swagger
open http://localhost:8200/docs
```

### 4. Première clé API

```bash
docker compose exec core python -m tik_core.scripts.create_api_key --bot zeta
# -> affiche la clé, à stocker dans le .env de ton bot client
```

---

## Structure du code

```
core/
├── src/tik_core/
│   ├── main.py                 # FastAPI app factory
│   ├── config.py               # chargement config + env
│   ├── api/                    # endpoints REST + WS
│   ├── auth/                   # middleware auth pluggable (API key / OAuth2 futur)
│   ├── storage/                # modèles SQLAlchemy + TimescaleDB helpers
│   ├── aggregator/             # 9 couches de données (ingesters)
│   ├── scoring/                # véracité, fake news, engines flash/swing/macro
│   ├── adapters/               # domain adapters (trading, betting…)
│   └── ml/                     # NLP sentiment, classifieur fake news
├── tests/
├── migrations/                 # Alembic
├── scripts/                    # CLI utilitaires
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── alembic.ini
└── .env.example
```

---

## Évolutions prévues

- [ ] Ingestor on-chain (Blockchain.com, Mempool.space)
- [ ] Ingestor news avec NLP sentiment (Ollama)
- [ ] Pipeline anti-fake-news complet
- [ ] Engines flash + macro (seul swing est implémenté dans le MVP)
- [ ] Endpoint `/feedback` pour PnL retour des clients
- [ ] Service backtest
- [ ] Passage à OAuth2 (provider prévu dans le code, cf. ADR-001)

---

© 2026 — Tik
