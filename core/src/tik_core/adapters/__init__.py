"""Domain adapters — traduisent les entities abstraites en concepts métier.

Permet à Tik d'être domain-agnostic : un entity "BTC" est traduit différemment
selon le domaine (trading → mapping Binance ; betting → mapping odds API).

MVP : seul l'adapter trading est implémenté. betting/politics/weather suivront.
"""

from tik_core.adapters.base import DomainAdapter
from tik_core.adapters.trading import TradingAdapter

__all__ = ["DomainAdapter", "TradingAdapter"]
