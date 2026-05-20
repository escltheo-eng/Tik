"""Interface de base des ingesters de données."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class MarketTick:
    """Tick de marché normalisé."""

    entity_id: str  # "BTC", "GOLD"
    source: str  # "binance", "yahoo"
    price: float
    volume: float | None = None
    timestamp: datetime = None  # type: ignore[assignment]
    extra: dict[str, Any] | None = None


@dataclass
class MacroDataPoint:
    """Point macro normalisé."""

    series_id: str  # "DGS10", "CPIAUCSL"
    source: str  # "fred"
    value: float
    timestamp: datetime
    extra: dict[str, Any] | None = None


class BaseIngester(ABC):
    """Interface commune des ingesters."""

    name: str = "base"
    layer: int = 0  # 1..9 selon l'archi

    @abstractmethod
    async def start(self) -> None:
        """Lance l'ingestion (boucle infinie ou subscribe)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Arrête proprement."""
        ...
