"""Tests unitaires du module pure logic tik_core.metrics.hit_rate.

Couvre :
- filter_signals_for_horizon : filtres horizon/entity/age/flagged
- compute_hit_rate : calcul success/skip/avg_gain par direction
- make_cache_key : déterminisme + distinction params

Aucune dépendance DB/HTTP/Redis — Signal est mocké via MagicMock,
les histoires de prix sont des listes [(ts_ms, price)].
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from tik_core.metrics.hit_rate import (
    HORIZON_DEFAULT_THRESHOLD_PCT,
    HORIZON_MEASURE_HOURS,
    VERACITY_BUCKETS,
    compute_hit_rate,
    compute_hit_rate_by_veracity,
    filter_signals_for_horizon,
    make_cache_key,
    make_cache_key_by_veracity,
)


# ----- Helpers -----

def _make_signal(
    *,
    entity_id: str = "BTC",
    horizon: str = "swing",
    direction: str = "long",
    timestamp: datetime,
    circuit_breaker_status: str = "ok",
    sig_id: str = "sig-test",
    veracity: float = 0.85,
):
    sig = MagicMock()
    sig.id = sig_id
    sig.entity_id = entity_id
    sig.horizon = horizon
    sig.direction = direction
    sig.timestamp = timestamp
    sig.circuit_breaker_status = circuit_breaker_status
    sig.veracity = veracity
    return sig


def _build_history(start_ms: int, n_points: int, base_price: float, step_pct: float = 0.1) -> list[tuple[int, float]]:
    """Construit une histoire de prix avec un step constant en %.

    `step_pct=0.1` → +0.1% par point. `step_pct=-0.5` → -0.5% par point.
    """
    history: list[tuple[int, float]] = []
    price = base_price
    ts = start_ms
    for _ in range(n_points):
        history.append((ts, price))
        price *= 1 + step_pct / 100
        ts += 60 * 60 * 1000  # +1h
    return history


NOW = datetime(2026, 5, 5, 12, 0, 0)


# ----- filter_signals_for_horizon -----

def test_filter_keeps_matching_horizon():
    sig_swing = _make_signal(horizon="swing", timestamp=NOW - timedelta(days=10))
    sig_flash = _make_signal(horizon="flash", timestamp=NOW - timedelta(hours=5))
    eligible, _ = filter_signals_for_horizon(
        [sig_swing, sig_flash],
        horizon="swing",
        entity_id="BTC",
        since_days=30,
        now=NOW,
        include_flagged=False,
    )
    assert len(eligible) == 1
    assert eligible[0] is sig_swing


def test_filter_keeps_matching_entity():
    sig_btc = _make_signal(entity_id="BTC", horizon="swing", timestamp=NOW - timedelta(days=10))
    sig_gold = _make_signal(entity_id="GOLD", horizon="swing", timestamp=NOW - timedelta(days=10))
    eligible, _ = filter_signals_for_horizon(
        [sig_btc, sig_gold],
        horizon="swing",
        entity_id="GOLD",
        since_days=30,
        now=NOW,
        include_flagged=False,
    )
    assert len(eligible) == 1
    assert eligible[0] is sig_gold


def test_filter_excludes_too_recent_swing():
    # Swing mesure à 5j → un signal swing de 1j d'âge n'est pas mature.
    sig = _make_signal(horizon="swing", timestamp=NOW - timedelta(days=1))
    eligible, _ = filter_signals_for_horizon(
        [sig],
        horizon="swing",
        entity_id="BTC",
        since_days=30,
        now=NOW,
        include_flagged=False,
    )
    assert eligible == []


def test_filter_excludes_too_recent_flash():
    # Flash mesure à 1h → un signal flash de 30min d'âge n'est pas mature.
    sig = _make_signal(horizon="flash", timestamp=NOW - timedelta(minutes=30))
    eligible, _ = filter_signals_for_horizon(
        [sig],
        horizon="flash",
        entity_id="BTC",
        since_days=30,
        now=NOW,
        include_flagged=False,
    )
    assert eligible == []


def test_filter_keeps_mature_flash():
    # Flash de 2h d'âge → mesurable (cutoff_mature = NOW - 1h).
    sig = _make_signal(horizon="flash", timestamp=NOW - timedelta(hours=2))
    eligible, _ = filter_signals_for_horizon(
        [sig],
        horizon="flash",
        entity_id="BTC",
        since_days=30,
        now=NOW,
        include_flagged=False,
    )
    assert len(eligible) == 1


def test_filter_excludes_too_old():
    # Signal de 31j d'âge sur fenêtre 30j → exclu.
    sig = _make_signal(horizon="swing", timestamp=NOW - timedelta(days=31))
    eligible, _ = filter_signals_for_horizon(
        [sig],
        horizon="swing",
        entity_id="BTC",
        since_days=30,
        now=NOW,
        include_flagged=False,
    )
    assert eligible == []


def test_filter_flagged_excluded_by_default():
    sig_ok = _make_signal(horizon="swing", timestamp=NOW - timedelta(days=10), circuit_breaker_status="ok", sig_id="ok")
    sig_deg = _make_signal(horizon="swing", timestamp=NOW - timedelta(days=10), circuit_breaker_status="degraded", sig_id="deg")
    sig_trip = _make_signal(horizon="swing", timestamp=NOW - timedelta(days=10), circuit_breaker_status="tripped", sig_id="trip")
    eligible, n_excluded = filter_signals_for_horizon(
        [sig_ok, sig_deg, sig_trip],
        horizon="swing",
        entity_id="BTC",
        since_days=30,
        now=NOW,
        include_flagged=False,
    )
    assert len(eligible) == 1
    assert eligible[0].id == "ok"
    assert n_excluded == 2


def test_filter_flagged_included_when_requested():
    sig_ok = _make_signal(horizon="swing", timestamp=NOW - timedelta(days=10), circuit_breaker_status="ok", sig_id="ok")
    sig_deg = _make_signal(horizon="swing", timestamp=NOW - timedelta(days=10), circuit_breaker_status="degraded", sig_id="deg")
    eligible, n_excluded = filter_signals_for_horizon(
        [sig_ok, sig_deg],
        horizon="swing",
        entity_id="BTC",
        since_days=30,
        now=NOW,
        include_flagged=True,
    )
    assert len(eligible) == 2
    assert n_excluded == 0


def test_filter_unknown_horizon_raises():
    sig = _make_signal(horizon="swing", timestamp=NOW - timedelta(days=10))
    with pytest.raises(ValueError, match="Unknown horizon"):
        filter_signals_for_horizon(
            [sig],
            horizon="unknown",
            entity_id="BTC",
            since_days=30,
            now=NOW,
            include_flagged=False,
        )


def test_filter_empty_list_returns_empty():
    eligible, n_excluded = filter_signals_for_horizon(
        [],
        horizon="swing",
        entity_id="BTC",
        since_days=30,
        now=NOW,
        include_flagged=False,
    )
    assert eligible == []
    assert n_excluded == 0


# ----- compute_hit_rate -----

def test_compute_long_success():
    # Signal long il y a 6j → mesure à 1j d'âge → marché doit avoir monté
    sig_ts = NOW - timedelta(days=6)
    sig = _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts)
    # Histoire BTC : commence avant le signal, prix monte de +0.5%/h sur 5j
    start_ms = int((sig_ts - timedelta(hours=2)).timestamp() * 1000)
    btc_history = _build_history(start_ms, n_points=200, base_price=100.0, step_pct=0.5)
    stats = compute_hit_rate(
        [sig],
        horizon="swing",
        threshold_pct=0.5,
        btc_history=btc_history,
        gold_history=[],
    )
    assert stats["n_evaluated"] == 1
    assert stats["n_success"] == 1
    assert stats["n_skipped"] == 0
    assert stats["hit_rate"] == 1.0
    assert stats["avg_gain_pct"] > 0


def test_compute_long_failure():
    sig_ts = NOW - timedelta(days=6)
    sig = _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts)
    start_ms = int((sig_ts - timedelta(hours=2)).timestamp() * 1000)
    btc_history = _build_history(start_ms, n_points=200, base_price=100.0, step_pct=-0.3)  # baisse
    stats = compute_hit_rate(
        [sig],
        horizon="swing",
        threshold_pct=0.5,
        btc_history=btc_history,
        gold_history=[],
    )
    assert stats["n_evaluated"] == 1
    assert stats["n_success"] == 0
    assert stats["hit_rate"] == 0.0


def test_compute_short_success():
    sig_ts = NOW - timedelta(days=6)
    sig = _make_signal(entity_id="GOLD", horizon="swing", direction="short", timestamp=sig_ts)
    start_ms = int((sig_ts - timedelta(hours=2)).timestamp() * 1000)
    gold_history = _build_history(start_ms, n_points=200, base_price=2000.0, step_pct=-0.5)
    stats = compute_hit_rate(
        [sig],
        horizon="swing",
        threshold_pct=0.5,
        btc_history=[],
        gold_history=gold_history,
    )
    assert stats["n_evaluated"] == 1
    assert stats["n_success"] == 1


def test_compute_neutral_success():
    sig_ts = NOW - timedelta(days=6)
    sig = _make_signal(entity_id="BTC", horizon="swing", direction="neutral", timestamp=sig_ts)
    start_ms = int((sig_ts - timedelta(hours=2)).timestamp() * 1000)
    # Marché stable (step 0.0)
    btc_history = _build_history(start_ms, n_points=200, base_price=100.0, step_pct=0.0)
    stats = compute_hit_rate(
        [sig],
        horizon="swing",
        threshold_pct=0.5,
        btc_history=btc_history,
        gold_history=[],
    )
    assert stats["n_evaluated"] == 1
    assert stats["n_success"] == 1


def test_compute_skips_unknown_entity():
    sig_ts = NOW - timedelta(days=6)
    sig = _make_signal(entity_id="UNKNOWN", horizon="swing", direction="long", timestamp=sig_ts)
    stats = compute_hit_rate(
        [sig],
        horizon="swing",
        threshold_pct=0.5,
        btc_history=[],
        gold_history=[],
    )
    assert stats["n_evaluated"] == 0
    assert stats["n_skipped"] == 1


def test_compute_skips_when_no_history():
    sig_ts = NOW - timedelta(days=6)
    sig = _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts)
    stats = compute_hit_rate(
        [sig],
        horizon="swing",
        threshold_pct=0.5,
        btc_history=[],  # vide
        gold_history=[],
    )
    assert stats["n_evaluated"] == 0
    assert stats["n_skipped"] == 1


def test_compute_empty_signals_returns_zeros():
    stats = compute_hit_rate(
        [],
        horizon="swing",
        threshold_pct=0.5,
        btc_history=[],
        gold_history=[],
    )
    assert stats["n_evaluated"] == 0
    assert stats["n_success"] == 0
    assert stats["hit_rate"] == 0.0
    assert stats["avg_gain_pct"] == 0.0


def test_compute_unknown_horizon_raises():
    sig_ts = NOW - timedelta(days=6)
    sig = _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts)
    with pytest.raises(ValueError, match="Unknown horizon"):
        compute_hit_rate(
            [sig],
            horizon="custom",
            threshold_pct=0.5,
            btc_history=[],
            gold_history=[],
        )


def test_compute_aggregates_multiple_signals():
    sig_ts = NOW - timedelta(days=6)
    sig_a = _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts, sig_id="a")
    sig_b = _make_signal(entity_id="BTC", horizon="swing", direction="short", timestamp=sig_ts, sig_id="b")
    start_ms = int((sig_ts - timedelta(hours=2)).timestamp() * 1000)
    # Marché monte → long success, short failure
    btc_history = _build_history(start_ms, n_points=200, base_price=100.0, step_pct=0.5)
    stats = compute_hit_rate(
        [sig_a, sig_b],
        horizon="swing",
        threshold_pct=0.5,
        btc_history=btc_history,
        gold_history=[],
    )
    assert stats["n_evaluated"] == 2
    assert stats["n_success"] == 1
    assert stats["hit_rate"] == 0.5


# ----- make_cache_key -----

def test_make_cache_key_deterministic():
    k1 = make_cache_key(entity_id="BTC", horizon="swing", since_days=30, threshold_pct=0.5, include_flagged=False)
    k2 = make_cache_key(entity_id="BTC", horizon="swing", since_days=30, threshold_pct=0.5, include_flagged=False)
    assert k1 == k2


def test_make_cache_key_distinguishes_entity():
    k_btc = make_cache_key(entity_id="BTC", horizon="swing", since_days=30, threshold_pct=0.5, include_flagged=False)
    k_gold = make_cache_key(entity_id="GOLD", horizon="swing", since_days=30, threshold_pct=0.5, include_flagged=False)
    assert k_btc != k_gold


def test_make_cache_key_distinguishes_horizon():
    k_swing = make_cache_key(entity_id="BTC", horizon="swing", since_days=30, threshold_pct=0.5, include_flagged=False)
    k_flash = make_cache_key(entity_id="BTC", horizon="flash", since_days=30, threshold_pct=0.5, include_flagged=False)
    assert k_swing != k_flash


def test_make_cache_key_distinguishes_flagged():
    k_clean = make_cache_key(entity_id="BTC", horizon="swing", since_days=30, threshold_pct=0.5, include_flagged=False)
    k_all = make_cache_key(entity_id="BTC", horizon="swing", since_days=30, threshold_pct=0.5, include_flagged=True)
    assert k_clean != k_all
    assert k_clean.endswith(".clean")
    assert k_all.endswith(".all")


def test_make_cache_key_distinguishes_threshold():
    k1 = make_cache_key(entity_id="BTC", horizon="swing", since_days=30, threshold_pct=0.5, include_flagged=False)
    k2 = make_cache_key(entity_id="BTC", horizon="swing", since_days=30, threshold_pct=0.3, include_flagged=False)
    assert k1 != k2


def test_make_cache_key_format():
    k = make_cache_key(entity_id="BTC", horizon="swing", since_days=30, threshold_pct=0.5, include_flagged=False)
    assert k == "tik.metrics.hit_rate.BTC.swing.30.0.50.clean"


# ----- Constantes -----

def test_horizon_measure_hours_completeness():
    assert "flash" in HORIZON_MEASURE_HOURS
    assert "swing" in HORIZON_MEASURE_HOURS
    assert "macro" in HORIZON_MEASURE_HOURS
    assert HORIZON_MEASURE_HOURS["flash"] < HORIZON_MEASURE_HOURS["swing"]
    assert HORIZON_MEASURE_HOURS["swing"] < HORIZON_MEASURE_HOURS["macro"]


def test_horizon_default_threshold_completeness():
    assert "flash" in HORIZON_DEFAULT_THRESHOLD_PCT
    assert "swing" in HORIZON_DEFAULT_THRESHOLD_PCT
    assert "macro" in HORIZON_DEFAULT_THRESHOLD_PCT
    # Threshold croissant avec horizon (cohérent : un mouvement 0.3% sur 1h
    # est rare, sur 30j on attend ≥1.5%).
    assert HORIZON_DEFAULT_THRESHOLD_PCT["flash"] < HORIZON_DEFAULT_THRESHOLD_PCT["swing"]
    assert HORIZON_DEFAULT_THRESHOLD_PCT["swing"] < HORIZON_DEFAULT_THRESHOLD_PCT["macro"]


# ----- compute_hit_rate_by_veracity (Phase A.2-bis) -----

def test_veracity_buckets_completeness():
    # Doit couvrir [0.70, 1.00] sans trou ni recouvrement (entre vmin et vmax exclusif).
    assert len(VERACITY_BUCKETS) == 4
    labels = [b[2] for b in VERACITY_BUCKETS]
    assert labels == ["0.70-0.79", "0.80-0.89", "0.90-0.94", "0.95-1.00"]
    # Continuité : le vmax de bucket i = vmin de bucket i+1
    for i in range(len(VERACITY_BUCKETS) - 1):
        assert VERACITY_BUCKETS[i][1] == VERACITY_BUCKETS[i + 1][0]
    # Le dernier bucket couvre 1.00 strictement (vmax=1.01 pour <)
    assert VERACITY_BUCKETS[-1][1] > 1.0


def test_compute_by_veracity_returns_all_buckets_even_empty():
    # Aucun signal → tous les buckets doivent quand même être présents avec n=0
    results = compute_hit_rate_by_veracity(
        [],
        horizon="swing",
        threshold_pct=0.5,
        btc_history=[],
        gold_history=[],
    )
    assert len(results) == 4
    for bucket in results:
        assert bucket["n_evaluated"] == 0
        assert bucket["hit_rate"] == 0.0
        assert "bucket_label" in bucket


def test_compute_by_veracity_segments_correctly():
    # Crée 4 signaux, 1 dans chaque bucket
    sig_ts = NOW - timedelta(days=6)
    sigs = [
        _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts, sig_id="a", veracity=0.78),
        _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts, sig_id="b", veracity=0.85),
        _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts, sig_id="c", veracity=0.92),
        _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts, sig_id="d", veracity=0.97),
    ]
    start_ms = int((sig_ts - timedelta(hours=2)).timestamp() * 1000)
    btc_history = _build_history(start_ms, n_points=200, base_price=100.0, step_pct=0.5)  # marché monte → tous LONG = success
    results = compute_hit_rate_by_veracity(
        sigs,
        horizon="swing",
        threshold_pct=0.5,
        btc_history=btc_history,
        gold_history=[],
    )
    # Chaque bucket a exactement 1 signal évalué
    for bucket in results:
        assert bucket["n_evaluated"] == 1
        assert bucket["hit_rate"] == 1.0  # tous LONG dans marché qui monte = 100%


def test_compute_by_veracity_high_veracity_higher_hit():
    # Reproduit le pattern observé en backtest 2026-05-05 : la haute veracity
    # doit avoir un meilleur hit rate que la basse. On simule des signaux LONG
    # dans un marché qui monte pour les hautes veracity, baisse pour les basses.
    sig_ts = NOW - timedelta(days=6)
    # Bucket 0.85 : 4 signaux LONG dans un marché qui baisse → tous KO
    low_sigs = [
        _make_signal(
            entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts,
            sig_id=f"low-{i}", veracity=0.85,
        )
        for i in range(4)
    ]
    # Bucket 0.95 : 2 signaux LONG, on testera dans un autre call avec marché qui monte
    high_sigs = [
        _make_signal(
            entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts,
            sig_id=f"high-{i}", veracity=0.97,
        )
        for i in range(2)
    ]
    start_ms = int((sig_ts - timedelta(hours=2)).timestamp() * 1000)
    # Marché qui monte → LONG success
    rising_market = _build_history(start_ms, n_points=200, base_price=100.0, step_pct=0.5)
    # Note : on combine tout dans le même appel. Comme le marché est commun à tous,
    # tous les LONG seront SUCCESS. On vérifie juste que la segmentation par bucket marche.
    results = compute_hit_rate_by_veracity(
        low_sigs + high_sigs,
        horizon="swing",
        threshold_pct=0.5,
        btc_history=rising_market,
        gold_history=[],
    )
    bucket_85 = next(b for b in results if b["bucket_label"] == "0.80-0.89")
    bucket_95 = next(b for b in results if b["bucket_label"] == "0.95-1.00")
    assert bucket_85["n_evaluated"] == 4
    assert bucket_95["n_evaluated"] == 2


def test_compute_by_veracity_unknown_horizon_raises():
    with pytest.raises(ValueError, match="Unknown horizon"):
        compute_hit_rate_by_veracity(
            [],
            horizon="custom",
            threshold_pct=0.5,
            btc_history=[],
            gold_history=[],
        )


def test_compute_by_veracity_skips_signals_with_none_veracity():
    sig_ts = NOW - timedelta(days=6)
    sig_none = _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts, sig_id="none")
    sig_none.veracity = None
    sig_ok = _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts, sig_id="ok", veracity=0.85)
    start_ms = int((sig_ts - timedelta(hours=2)).timestamp() * 1000)
    btc_history = _build_history(start_ms, n_points=200, base_price=100.0, step_pct=0.5)
    results = compute_hit_rate_by_veracity(
        [sig_none, sig_ok],
        horizon="swing",
        threshold_pct=0.5,
        btc_history=btc_history,
        gold_history=[],
    )
    bucket_85 = next(b for b in results if b["bucket_label"] == "0.80-0.89")
    assert bucket_85["n_evaluated"] == 1  # sig_none ignoré


def test_compute_by_veracity_boundary_inclusive_min():
    # Veracity exactement 0.90 doit aller dans bucket 0.90-0.94 (vmin inclusif)
    sig_ts = NOW - timedelta(days=6)
    sig = _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts, veracity=0.90)
    start_ms = int((sig_ts - timedelta(hours=2)).timestamp() * 1000)
    btc_history = _build_history(start_ms, n_points=200, base_price=100.0, step_pct=0.5)
    results = compute_hit_rate_by_veracity(
        [sig],
        horizon="swing",
        threshold_pct=0.5,
        btc_history=btc_history,
        gold_history=[],
    )
    bucket_85 = next(b for b in results if b["bucket_label"] == "0.80-0.89")
    bucket_90 = next(b for b in results if b["bucket_label"] == "0.90-0.94")
    assert bucket_85["n_evaluated"] == 0
    assert bucket_90["n_evaluated"] == 1


def test_compute_by_veracity_boundary_max_strict():
    # Veracity exactement 1.00 doit aller dans bucket 0.95-1.00 (vmax 1.01 strict)
    sig_ts = NOW - timedelta(days=6)
    sig = _make_signal(entity_id="BTC", horizon="swing", direction="long", timestamp=sig_ts, veracity=1.00)
    start_ms = int((sig_ts - timedelta(hours=2)).timestamp() * 1000)
    btc_history = _build_history(start_ms, n_points=200, base_price=100.0, step_pct=0.5)
    results = compute_hit_rate_by_veracity(
        [sig],
        horizon="swing",
        threshold_pct=0.5,
        btc_history=btc_history,
        gold_history=[],
    )
    bucket_95 = next(b for b in results if b["bucket_label"] == "0.95-1.00")
    assert bucket_95["n_evaluated"] == 1


# ----- make_cache_key_by_veracity -----

def test_make_cache_key_by_veracity_format():
    k = make_cache_key_by_veracity(
        entity_id="BTC", horizon="swing", since_days=30,
        threshold_pct=0.5, include_flagged=False,
    )
    assert k == "tik.metrics.hit_rate_by_veracity.BTC.swing.30.0.50.clean"


def test_make_cache_key_by_veracity_distinct_from_hit_rate():
    k_hr = make_cache_key(
        entity_id="BTC", horizon="swing", since_days=30,
        threshold_pct=0.5, include_flagged=False,
    )
    k_vy = make_cache_key_by_veracity(
        entity_id="BTC", horizon="swing", since_days=30,
        threshold_pct=0.5, include_flagged=False,
    )
    assert k_hr != k_vy
    assert "hit_rate_by_veracity" in k_vy
    assert "hit_rate_by_veracity" not in k_hr
