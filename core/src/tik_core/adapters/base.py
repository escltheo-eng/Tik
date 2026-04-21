"""Interface abstraite des domain adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EntityMapping:
    """Mapping d'une entity vers les concepts du domaine."""

    entity_id: str
    native_symbols: dict[str, str]  # ex: {"binance": "BTCUSDT", "yahoo": "BTC-USD"}
    metadata: dict


class DomainAdapter(ABC):
    """Interface d'un adapter de domaine.

    Les adapters concrets (trading, betting, politics, weather) savent traduire
    les `Entity` en concepts métier et produire l'advisory spécifique au domaine
    à inclure dans les signaux.
    """

    domain: str = "generic"

    @abstractmethod
    def resolve_mapping(self, entity_id: str) -> EntityMapping | None:
        """Retourne le mapping natif pour cette entity."""
        ...

    @abstractmethod
    def build_advisory(self, entity_id: str, direction: str, confidence: float) -> dict:
        """Construit l'advisory du signal pour ce domaine."""
        ...
