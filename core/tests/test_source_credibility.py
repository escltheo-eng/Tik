"""Tests du scoring source dynamique (anti fake-news, ADR-011).

Couverture : logique pure d'ajustement, context-var dynamic_scores,
lecture/écriture Redis (FakeRedis), agrégation des hit rates, recalibration
unitaire.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from tik_core.scoring.source_credibility import (
    HORIZON_DAYS,
    LOOKBACK_DAYS,
    MAX_SCORE,
    MIN_SAMPLES,
    MIN_SCORE,
    PENALTY_FACTOR,
    RECALIBRATION_DATA_FLOOR,
    REDIS_KEY_TPL,
    REWARD_FACTOR,
    SCORE_TTL_SEC,
    _capped,
    _compute_adjustment,
    _compute_hit_rates_by_source,
    _lookback_window,
    get_effective_score,
    get_source_score,
    preload_source_scores,
    recalibrate_source,
    reset_dynamic_scores,
    set_dynamic_scores,
    set_source_score,
)
from tik_core.utils.time import now_utc_naive

# ----- Fakes minimaux -----


class FakeRedis:
    """Implémentation minimale du contrat redis.asyncio utilisé ici."""

    def __init__(self, data: dict | None = None):
        self.data: dict[str, str] = data or {}
        self.setex_calls: list[tuple[str, int, str]] = []

    async def get(self, key: str):
        return self.data.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value
        self.setex_calls.append((key, ttl, value))


class FakeSession:
    """Simule AsyncSession.add (sync, append à une liste interne)."""

    def __init__(self):
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)


def _make_signal(
    entity_id: str,
    direction: str,
    timestamp: datetime,
    sources: list[str],
    sig_id: str = "sig-test",
):
    """Construit un Signal minimaliste pour les tests."""
    sig = MagicMock()
    sig.id = sig_id
    sig.entity_id = entity_id
    sig.direction = direction
    sig.timestamp = timestamp
    sig.evidence = [{"source": s, "score": 0.7, "fact": "..."} for s in sources]
    return sig


# =====================================================================
# _capped
# =====================================================================


def test_capped_above_max_returns_max():
    assert _capped(1.5) == MAX_SCORE


def test_capped_below_min_returns_min():
    assert _capped(0.1) == MIN_SCORE


def test_capped_in_range_unchanged():
    assert _capped(0.5) == 0.5


# =====================================================================
# _compute_adjustment (logique pure)
# =====================================================================


def test_adjustment_too_few_samples_unchanged():
    new, kind = _compute_adjustment(0.7, 0.30, MIN_SAMPLES - 1)
    assert kind == "unchanged"
    assert new == 0.7


def test_adjustment_low_hit_rate_penalty():
    # hit_rate < 40% → ÷1.2
    new, kind = _compute_adjustment(0.7, 0.20, MIN_SAMPLES + 10)
    assert kind == "penalty"
    assert new == round(0.7 / PENALTY_FACTOR, 4)


def test_adjustment_high_hit_rate_reward():
    new, kind = _compute_adjustment(0.7, 0.80, MIN_SAMPLES + 10)
    assert kind == "reward"
    assert new == round(0.7 * REWARD_FACTOR, 4)


def test_adjustment_neutral_hit_rate_unchanged():
    # 40% ≤ hit_rate ≤ 70% → unchanged
    new, kind = _compute_adjustment(0.7, 0.55, 100)
    assert kind == "unchanged"
    assert new == 0.7


def test_adjustment_penalty_capped_at_min():
    # Score déjà bas, penalty cap MIN_SCORE
    new, kind = _compute_adjustment(0.32, 0.10, 100)
    assert kind == "penalty"
    assert new == MIN_SCORE


def test_adjustment_reward_capped_at_max():
    # Score déjà haut, reward cap MAX_SCORE
    new, kind = _compute_adjustment(0.92, 0.95, 100)
    assert kind == "reward"
    assert new == MAX_SCORE


def test_adjustment_asymmetry_penalty_stronger_than_reward():
    # Le facteur penalty (÷1.2) est plus fort que le reward (×1.1) à dirstance égale
    base = 0.5
    after_penalty, _ = _compute_adjustment(base, 0.20, 100)
    after_reward, _ = _compute_adjustment(base, 0.80, 100)
    drop = base - after_penalty
    rise = after_reward - base
    assert drop > rise  # asymétrie cohérente paranoïa contrôlée


# =====================================================================
# context-var dynamic_scores
# =====================================================================


def test_get_effective_score_no_context_returns_fallback():
    fallback = {"source_a": 0.7}
    score = get_effective_score("source_a", fallback)
    assert score == 0.7


def test_get_effective_score_unknown_source_returns_default_05():
    score = get_effective_score("nonexistent", {})
    assert score == 0.5


def test_get_effective_score_with_dynamic_overrides_fallback():
    fallback = {"source_a": 0.7}
    token = set_dynamic_scores({"source_a": 0.85})
    try:
        assert get_effective_score("source_a", fallback) == 0.85
    finally:
        reset_dynamic_scores(token)


def test_get_effective_score_dynamic_partial_falls_back_for_missing():
    fallback = {"source_a": 0.7, "source_b": 0.6}
    token = set_dynamic_scores({"source_a": 0.85})
    try:
        assert get_effective_score("source_a", fallback) == 0.85  # dynamique
        assert get_effective_score("source_b", fallback) == 0.6  # fallback
    finally:
        reset_dynamic_scores(token)


def test_reset_dynamic_scores_restores_fallback():
    fallback = {"source_a": 0.7}
    token = set_dynamic_scores({"source_a": 0.99})
    reset_dynamic_scores(token)
    assert get_effective_score("source_a", fallback) == 0.7


# =====================================================================
# Redis read/write
# =====================================================================


@pytest.mark.asyncio
async def test_get_source_score_redis_none_returns_none():
    score = await get_source_score(None, "source_a")
    assert score is None


@pytest.mark.asyncio
async def test_get_source_score_redis_miss_returns_none():
    redis = FakeRedis()
    score = await get_source_score(redis, "source_a")
    assert score is None


@pytest.mark.asyncio
async def test_get_source_score_redis_hit_returns_value():
    redis = FakeRedis({REDIS_KEY_TPL.format(source="source_a"): "0.85"})
    score = await get_source_score(redis, "source_a")
    assert score == 0.85


@pytest.mark.asyncio
async def test_get_source_score_invalid_value_returns_none():
    redis = FakeRedis({REDIS_KEY_TPL.format(source="source_a"): "not_a_number"})
    score = await get_source_score(redis, "source_a")
    assert score is None


@pytest.mark.asyncio
async def test_set_source_score_writes_with_cap():
    redis = FakeRedis()
    score = await set_source_score(redis, "source_a", 1.5)
    assert score == MAX_SCORE
    key = REDIS_KEY_TPL.format(source="source_a")
    assert redis.data[key] == f"{MAX_SCORE:.4f}"


@pytest.mark.asyncio
async def test_set_source_score_below_min_caps():
    redis = FakeRedis()
    score = await set_source_score(redis, "source_a", 0.1)
    assert score == MIN_SCORE


@pytest.mark.asyncio
async def test_set_source_score_uses_default_ttl():
    redis = FakeRedis()
    await set_source_score(redis, "source_a", 0.7)
    assert redis.setex_calls[0][1] == SCORE_TTL_SEC


# =====================================================================
# preload_source_scores
# =====================================================================


@pytest.mark.asyncio
async def test_preload_returns_only_redis_hits():
    redis = FakeRedis(
        {
            REDIS_KEY_TPL.format(source="source_a"): "0.85",
            # source_b absent
        }
    )
    scores = await preload_source_scores(redis, ["source_a", "source_b"])
    assert scores == {"source_a": 0.85}


@pytest.mark.asyncio
async def test_preload_redis_none_returns_empty_dict():
    scores = await preload_source_scores(None, ["source_a"])
    assert scores == {}


# =====================================================================
# _compute_hit_rates_by_source
# =====================================================================


def test_compute_hit_rates_btc_long_success():
    now = now_utc_naive()
    ts0 = now - timedelta(days=10)
    # delta +2% → long success
    sig = _make_signal("BTC", "long", ts0, ["alternative_me_fng", "google_news_rss"])

    btc_history = [
        (int(ts0.replace(tzinfo=UTC).timestamp() * 1000), 100.0),
        (int((ts0 + timedelta(days=5)).replace(tzinfo=UTC).timestamp() * 1000), 102.0),
    ]
    rates = _compute_hit_rates_by_source([sig], btc_history, [])
    assert rates["alternative_me_fng"] == (1, 1)
    assert rates["google_news_rss"] == (1, 1)


def test_compute_hit_rates_btc_short_failure():
    now = now_utc_naive()
    ts0 = now - timedelta(days=10)
    sig = _make_signal("BTC", "short", ts0, ["reddit_btc"])

    btc_history = [
        (int(ts0.replace(tzinfo=UTC).timestamp() * 1000), 100.0),
        (int((ts0 + timedelta(days=5)).replace(tzinfo=UTC).timestamp() * 1000), 105.0),
    ]
    rates = _compute_hit_rates_by_source([sig], btc_history, [])
    # short prediction quand le marché monte → échec
    assert rates["reddit_btc"] == (0, 1)


def test_compute_hit_rates_filters_non_recalibratable():
    now = now_utc_naive()
    ts0 = now - timedelta(days=10)
    # source binance_klines n'est PAS dans RECALIBRATABLE_SOURCES → ignorée
    sig = _make_signal("BTC", "long", ts0, ["binance_klines", "alternative_me_fng"])

    btc_history = [
        (int(ts0.replace(tzinfo=UTC).timestamp() * 1000), 100.0),
        (int((ts0 + timedelta(days=5)).replace(tzinfo=UTC).timestamp() * 1000), 102.0),
    ]
    rates = _compute_hit_rates_by_source([sig], btc_history, [])
    assert "binance_klines" not in rates
    assert rates["alternative_me_fng"] == (1, 1)


def test_compute_hit_rates_aggregates_multi_signal():
    now = now_utc_naive()
    ts0 = now - timedelta(days=10)
    sigs = [
        _make_signal("BTC", "long", ts0, ["alternative_me_fng"], sig_id="s1"),
        _make_signal("BTC", "short", ts0, ["alternative_me_fng"], sig_id="s2"),
    ]
    btc_history = [
        (int(ts0.replace(tzinfo=UTC).timestamp() * 1000), 100.0),
        (int((ts0 + timedelta(days=5)).replace(tzinfo=UTC).timestamp() * 1000), 102.0),
    ]
    rates = _compute_hit_rates_by_source(sigs, btc_history, [])
    # 1 succès (long) + 1 échec (short) → (1, 2)
    assert rates["alternative_me_fng"] == (1, 2)


# =====================================================================
# recalibrate_source (intégration partielle)
# =====================================================================


@pytest.mark.asyncio
async def test_recalibrate_source_unchanged_below_min_samples():
    redis = FakeRedis({REDIS_KEY_TPL.format(source="alternative_me_fng"): "0.65"})
    session = FakeSession()
    res = await recalibrate_source(redis, session, "alternative_me_fng", 5, 10)
    assert res.adjustment == "unchanged"
    assert res.previous_score == 0.65
    assert res.new_score == 0.65
    # Pas de write Redis (score inchangé)
    assert redis.setex_calls == []
    # Une row d'audit DB quand même
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_recalibrate_source_penalty_writes_redis():
    redis = FakeRedis({REDIS_KEY_TPL.format(source="alternative_me_fng"): "0.65"})
    session = FakeSession()
    # 30+ samples, hit rate < 40% → penalty
    res = await recalibrate_source(redis, session, "alternative_me_fng", 8, 40)
    assert res.adjustment == "penalty"
    assert res.new_score < res.previous_score
    assert len(redis.setex_calls) == 1


@pytest.mark.asyncio
async def test_recalibrate_source_uses_static_fallback_when_redis_empty():
    # Première recalibration : Redis vide → fallback static (SOURCE_SCORES["alternative_me_fng"] = 0.65)
    redis = FakeRedis()
    session = FakeSession()
    res = await recalibrate_source(redis, session, "alternative_me_fng", 8, 40)
    assert res.previous_score == 0.65  # SOURCE_SCORES static


@pytest.mark.asyncio
async def test_recalibrate_source_reward_path():
    redis = FakeRedis({REDIS_KEY_TPL.format(source="alternative_me_fng"): "0.65"})
    session = FakeSession()
    res = await recalibrate_source(redis, session, "alternative_me_fng", 35, 40)
    assert res.adjustment == "reward"
    assert res.new_score > res.previous_score


# ----- Plancher de données R2/R6 (Paquet 34) -----


def test_lookback_window_applies_floor_when_30d_before_fix():
    """now peu après le fix : now-30j est avant le plancher → start = plancher."""
    now = RECALIBRATION_DATA_FLOOR + timedelta(days=10)
    start, end = _lookback_window(now)
    # now-30j = ~2026-04-27 < floor (2026-05-17) → le plancher prime
    assert start == RECALIBRATION_DATA_FLOOR
    assert end == now - timedelta(days=HORIZON_DAYS)
    # fenêtre non vide à J+10 → la recalibration peut reprendre sur du propre
    assert start < end


def test_lookback_window_ignores_floor_when_30d_after_fix():
    """now loin dans le futur : now-30j dépasse le plancher → borne glissante normale."""
    now = RECALIBRATION_DATA_FLOOR + timedelta(days=100)
    start, end = _lookback_window(now)
    assert start == now - timedelta(days=LOOKBACK_DAYS)
    assert start > RECALIBRATION_DATA_FLOOR
    assert end == now - timedelta(days=HORIZON_DAYS)


def test_lookback_window_empty_when_no_clean_matured_data():
    """now = fix + 3j : la borne de maturité (now-5j) est avant le plancher → fenêtre vide."""
    now = RECALIBRATION_DATA_FLOOR + timedelta(days=3)
    start, end = _lookback_window(now)
    # end = fix - 2j < start = floor → start >= end → le caller doit skip
    assert start >= end


def test_lookback_window_custom_floor():
    """Le plancher est paramétrable (testabilité, future réutilisation)."""
    custom = datetime(2026, 1, 1, 0, 0, 0)
    now = custom + timedelta(days=10)
    start, end = _lookback_window(now, floor=custom)
    assert start == custom
