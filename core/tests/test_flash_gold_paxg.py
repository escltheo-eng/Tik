"""Tests flash GOLD via proxy PAXG (ADR-040) — logique pure, sans réseau.

Couvre : les heures d'ouverture du marché or (le skip week-end), la présence
des specs PAXG (score source, params de mesure), et la cohérence du câblage
metrics (le fail-fast flash GOLD a été retiré, micro GOLD le garde).
"""

from datetime import UTC, datetime

from tik_core.scoring.flash_engine import (
    FLASH_SOURCE_SCORES,
    PAXG_KLINE_STALE_SEC,
    is_gold_market_open,
)


class TestGoldMarketHours:
    def test_open_midweek(self):
        # Mercredi 12:00 UTC → ouvert.
        assert is_gold_market_open(datetime(2026, 7, 1, 12, 0, tzinfo=UTC)) is True

    def test_closed_friday_night(self):
        # Vendredi 21:00 UTC → fermé (clôture COMEX).
        assert is_gold_market_open(datetime(2026, 7, 3, 21, 0, tzinfo=UTC)) is False
        # Vendredi 20:59 → encore ouvert.
        assert is_gold_market_open(datetime(2026, 7, 3, 20, 59, tzinfo=UTC)) is True

    def test_closed_saturday(self):
        assert is_gold_market_open(datetime(2026, 7, 4, 12, 0, tzinfo=UTC)) is False

    def test_sunday_reopen(self):
        # Dimanche 21:59 → fermé ; 22:00 → réouvert.
        assert is_gold_market_open(datetime(2026, 7, 5, 21, 59, tzinfo=UTC)) is False
        assert is_gold_market_open(datetime(2026, 7, 5, 22, 0, tzinfo=UTC)) is True


class TestPaxgSpecs:
    def test_paxg_source_score_lower_than_btc(self):
        # Proxy + carnet moins liquide → crédibilité PAXG < BTC (ADR-040).
        assert FLASH_SOURCE_SCORES["binance_paxg_klines_1m"] < FLASH_SOURCE_SCORES["binance_klines_1m"]

    def test_stale_threshold_defined(self):
        assert PAXG_KLINE_STALE_SEC == 180


class TestMetricsWiring:
    def test_flash_gold_no_longer_fail_fast(self):
        # Le 400 « pas de flash GOLD » ne doit plus viser flash (mesure PAXG),
        # seulement micro. Garde-fou code-source (pattern Bug 10).
        import inspect

        from tik_core.api import metrics

        src = inspect.getsource(metrics)
        assert 'signal.horizon == "micro" and signal.entity_id == "GOLD"' in src
        assert 'signal.horizon in ("flash", "micro") and signal.entity_id == "GOLD"' not in src
        assert "fetch_paxg_history" in src

    def test_scheduler_has_flash_gold_job(self):
        # Lecture texte (pas d'import) : run_scheduler importe apscheduler,
        # absent de certains environnements de test minimaux.
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "tik_core"
            / "scripts"
            / "run_scheduler.py"
        ).read_text(encoding="utf-8")
        assert 'id="flash_gold"' in src
        assert "analyze_flash_gold" in src
