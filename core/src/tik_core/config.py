"""Configuration globale Tik Core.

Charge les variables d'environnement via Pydantic Settings.
Pour override en test : créer un .env.test ou passer via fixture.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Paramètres Tik Core."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TIK_",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Environnement ---
    env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8200

    # --- Sécurité ---
    secret_key: str = Field(default="dev-secret-change-me", min_length=16)
    auth_provider: Literal["api_key", "oauth2"] = "api_key"

    # --- Database ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "tik"
    db_user: str = "tik"
    db_password: str = "tik_dev"

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # --- APIs externes ---
    fred_api_key: str = ""
    cryptopanic_api_key: str = ""
    cryptocompare_api_key: str = ""

    # --- News classifier (sentiment textuel) ---
    news_classifier: Literal["ollama", "keywords"] = "ollama"
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.2:3b"

    # --- Scoring defaults ---
    default_min_veracity: float = 0.70
    default_min_sources: int = 2

    # --- Anti fake-news (ADR-011) ---
    # active : cross-validation modifie circuit_breaker_status + direction si tripped
    # shadow : cross-validation calcule mais n'affecte pas la décision (logs uniquement)
    antifakenews_mode: Literal["active", "shadow"] = "active"

    # --- LLM hypothesis generator (ADR-012) ---
    # Implémentation utilisée pour synthétiser l'hypothèse contextuelle.
    # ollama   : appel LLM local (llama3.2:3b par défaut, partage la même
    #            infra Ollama que le news_classifier — cf. ADR-006).
    # template : f-string déterministe historique (pas d'appel LLM).
    llm_hypothesis: Literal["ollama", "template"] = "template"
    # disabled : aucun appel LLM, hypothèse template seule
    # shadow   : LLM exécuté, sortie stockée dans Signal.advisory
    #            ["llm_hypothesis_candidate"] pour validation passive ;
    #            Signal.hypothesis garde le texte template (sécurisé)
    # active   : LLM remplace Signal.hypothesis ; le template est conservé
    #            dans Signal.advisory["template_hypothesis"] pour audit
    llm_hypothesis_mode: Literal["disabled", "shadow", "active"] = "shadow"

    # --- Overlays GOLD calibrés (ADR-018 amendement P2) ---
    # DXY (contrarian) et CFTC COT (contrarian) mesurés inversés sur 12m
    # 2025-2026 (DXY IC Spearman +0.23 à 120h, COT IC +0.43 à 720h —
    # signes positifs au lieu de négatifs attendus contrarian). Régime
    # "tout monte" 2025-2026 (crypto + or + dollar fort en parallèle).
    # Désactivés par défaut, à réactiver post-J+30 après mesure sur
    # période bear pour confirmer si l'inversion est régime-spécifique.
    gold_dxy_cot_overlays_enabled: bool = False

    # --- Overlay CoinGecko sentiment (ADR-021, SHADOW) ---
    # Sentiment communautaire CoinGecko (vote up/down BTC) ajouté comme 4e
    # overlay candidat suite au ban IP de Reddit (Bug 11). DÉSACTIVÉ par défaut :
    # l'ingester collecte en shadow (Redis), l'overlay swing ne touche aux
    # signaux émis que si ce toggle passe à true — après mesure de la divergence
    # vs Fear & Greed (apport indépendant ?). Toggle env : TIK_COINGECKO_OVERLAY_ENABLED.
    coingecko_overlay_enabled: bool = False

    # --- CORS ---
    cors_origins: str = "http://localhost:3000"

    @property
    def database_url(self) -> str:
        """DSN Postgres asyncpg pour SQLAlchemy async."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def database_url_sync(self) -> str:
        """DSN Postgres psycopg2 pour Alembic."""
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def redis_url(self) -> str:
        """DSN Redis."""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    """Retourne les settings (singleton mémoïsé)."""
    return Settings()
