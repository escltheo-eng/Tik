"""Trading adapter — mapping BTC, Gold et autres actifs financiers.

Consommé par Zeta, Totem, et tout autre bot de trading.
"""

from tik_core.adapters.base import DomainAdapter, EntityMapping

_TRADING_MAPPINGS: dict[str, EntityMapping] = {
    "BTC": EntityMapping(
        entity_id="BTC",
        native_symbols={
            "binance": "BTCUSDT",
            "yahoo": "BTC-USD",
            "mt5": "BTCUSD",
            "coingecko": "bitcoin",
        },
        metadata={"asset_class": "crypto", "quote_currency": "USDT"},
    ),
    "GOLD": EntityMapping(
        entity_id="GOLD",
        native_symbols={
            "yahoo": "GC=F",
            "mt5": "XAUUSD",
            "exchangerate_host": "XAU",
        },
        metadata={"asset_class": "commodity", "quote_currency": "USD"},
    ),
}


class TradingAdapter(DomainAdapter):
    """Adapter pour le domaine trading."""

    domain = "trading"

    def resolve_mapping(self, entity_id: str) -> EntityMapping | None:
        return _TRADING_MAPPINGS.get(entity_id)

    def build_advisory(
        self,
        entity_id: str,  # noqa: ARG002 — conservé pour la signature d'interface advisory
        direction: str,
        confidence: float,
    ) -> dict:
        """Produit un advisory spécifique trading.

        N'influence PAS la décision de Zeta : purement informatif pour
        alimenter son risk_engine / turbo_monitoring.
        """
        # Règle simple : si confidence forte ET direction opposée à une position
        # hypothétique, suggérer de réduire. Le bot client applique ou ignore.
        if confidence >= 0.85 and direction != "neutral":
            bias = "reinforce" if direction == "long" else "reduce"
        elif confidence >= 0.70:
            bias = "neutral"
        else:
            bias = "neutral"

        return {
            "bias_on_existing_positions": bias,
            "macro_crash_warning": False,
            "notes": None,
        }
