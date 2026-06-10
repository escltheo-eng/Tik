"""Tests pour `core/src/tik_core/scoring/anomaly_detector.py` (P6 plan
fiabilité, Paquet 21).

Helpers purs, pas de Redis ni HTTP. Tests couvrent les 3 détecteurs et
leurs edge cases : échantillon insuffisant, données malformées, valeurs
extrêmes, frontières de seuils medium/high.
"""

from __future__ import annotations

from tik_core.scoring.anomaly_detector import (
    BRIGADING_MIN_POSTS,
    BRIGADING_THRESHOLD_HIGH,
    BRIGADING_THRESHOLD_MEDIUM,
    PUBLISHER_DIVERSITY_MIN_BASELINE_POINTS,
    PUBLISHER_DIVERSITY_SPIKE_THRESHOLD_HIGH,
    PUBLISHER_DIVERSITY_SPIKE_THRESHOLD_MEDIUM,
    PUBLISHER_DOMINANCE_MIN_TITLES,
    PUBLISHER_DOMINANCE_THRESHOLD_HIGH,
    PUBLISHER_DOMINANCE_THRESHOLD_MEDIUM,
    VOLUME_SPIKE_MIN_BASELINE_POINTS,
    VOLUME_SPIKE_THRESHOLD_HIGH,
    VOLUME_SPIKE_THRESHOLD_MEDIUM,
    detect_brigading_reddit,
    detect_publisher_diversity_spike,
    detect_publisher_dominance,
    detect_volume_spike,
)


class TestDetectBrigadingReddit:
    def test_empty_list_returns_ok(self):
        result = detect_brigading_reddit([])
        assert result["type"] == "brigading_reddit"
        assert result["severity"] == "ok"
        assert result["score"] == 0.0
        assert "insufficient sample" in result["detail"]

    def test_below_min_posts_returns_ok(self):
        posts = [{"score": 100, "num_comments": 50}] * (BRIGADING_MIN_POSTS - 1)
        result = detect_brigading_reddit(posts)
        assert result["severity"] == "ok"
        assert "insufficient" in result["detail"].lower()

    def test_all_invalid_posts_returns_ok(self):
        posts = [{"foo": "bar"}, {"baz": 42}, {"score": "abc"}]
        result = detect_brigading_reddit(posts)
        assert result["severity"] == "ok"

    def test_all_zero_upvotes_returns_ok(self):
        posts = [{"score": 0, "num_comments": 100}] * 10
        result = detect_brigading_reddit(posts)
        assert result["severity"] == "ok"

    def test_ratio_zero_comments_is_ok(self):
        posts = [{"score": 100, "num_comments": 0}] * 5
        result = detect_brigading_reddit(posts)
        assert result["severity"] == "ok"
        assert result["score"] == 0.0

    def test_ratio_low_is_ok(self):
        posts = [{"score": 1000, "num_comments": 100}] * 5  # ratio 0.1
        result = detect_brigading_reddit(posts)
        assert result["severity"] == "ok"
        assert result["score"] == 0.1

    def test_ratio_at_medium_threshold_is_medium(self):
        # Force ratio == BRIGADING_THRESHOLD_MEDIUM exactement
        n = int(100 * BRIGADING_THRESHOLD_MEDIUM)
        posts = [{"score": 100, "num_comments": n}] * 5
        result = detect_brigading_reddit(posts)
        assert result["severity"] == "medium"

    def test_ratio_above_medium_below_high_is_medium(self):
        # ratio = 0.75 (entre 0.5 et 1.0)
        posts = [{"score": 100, "num_comments": 75}] * 5
        result = detect_brigading_reddit(posts)
        assert result["severity"] == "medium"
        assert result["score"] == 0.75

    def test_ratio_at_high_threshold_is_high(self):
        # ratio == BRIGADING_THRESHOLD_HIGH (1.0) exactement
        n = int(100 * BRIGADING_THRESHOLD_HIGH)
        posts = [{"score": 100, "num_comments": n}] * 5
        result = detect_brigading_reddit(posts)
        assert result["severity"] == "high"

    def test_ratio_above_high_is_high(self):
        posts = [{"score": 100, "num_comments": 200}] * 5  # ratio 2.0
        result = detect_brigading_reddit(posts)
        assert result["severity"] == "high"
        assert result["score"] == 2.0

    def test_mixed_valid_invalid_uses_only_valid(self):
        posts = [
            {"score": 100, "num_comments": 200},  # valid
            {"score": 100, "num_comments": 200},  # valid
            {"score": 100, "num_comments": 200},  # valid
            {"foo": "bar"},  # invalid
            {"score": "abc", "num_comments": 50},  # invalid (string score)
        ]
        result = detect_brigading_reddit(posts)
        # 3 posts valides à ratio 2.0 chacun
        assert result["severity"] == "high"
        assert result["score"] == 2.0


class TestDetectPublisherDominance:
    def test_below_min_titles_returns_ok(self):
        result = detect_publisher_dominance(
            top_publishers=[{"name": "Reuters", "count": 4}],
            total_titles=PUBLISHER_DOMINANCE_MIN_TITLES - 1,
        )
        assert result["type"] == "publisher_dominance"
        assert result["severity"] == "ok"
        assert "insufficient" in result["detail"].lower()

    def test_empty_top_publishers_returns_ok(self):
        result = detect_publisher_dominance([], total_titles=20)
        assert result["severity"] == "ok"
        assert result["detail"] == "no publishers data"

    def test_malformed_top_publishers_returns_ok(self):
        result = detect_publisher_dominance(
            [{"name": "X", "count": "not a number"}],
            total_titles=20,
        )
        assert result["severity"] == "ok"

    def test_zero_count_returns_ok(self):
        result = detect_publisher_dominance(
            [{"name": "Reuters", "count": 0}],
            total_titles=20,
        )
        assert result["severity"] == "ok"

    def test_ratio_low_is_ok(self):
        result = detect_publisher_dominance(
            [{"name": "Reuters", "count": 4}],  # 4/20 = 20%
            total_titles=20,
        )
        assert result["severity"] == "ok"
        assert result["score"] == 0.2

    def test_ratio_at_medium_threshold_is_medium(self):
        # Force ratio == PUBLISHER_DOMINANCE_THRESHOLD_MEDIUM (0.42, recal. B.1).
        # total_titles=50 → le ratio tombe juste (0.42 = 21/50), contrairement
        # à 20 où int(20*0.42)=8 donnerait 0.40 < seuil.
        count = round(50 * PUBLISHER_DOMINANCE_THRESHOLD_MEDIUM)
        result = detect_publisher_dominance(
            [{"name": "Yahoo", "count": count}],
            total_titles=50,
        )
        assert result["severity"] == "medium"

    def test_ratio_at_high_threshold_is_high(self):
        # Force ratio == PUBLISHER_DOMINANCE_THRESHOLD_HIGH (0.50, recal. B.1)
        count = int(20 * PUBLISHER_DOMINANCE_THRESHOLD_HIGH)
        result = detect_publisher_dominance(
            [{"name": "Yahoo", "count": count}],
            total_titles=20,
        )
        assert result["severity"] == "high"

    def test_ratio_above_high_is_high(self):
        result = detect_publisher_dominance(
            [{"name": "Yahoo", "count": 18}],  # 18/20 = 90%
            total_titles=20,
        )
        assert result["severity"] == "high"
        assert result["score"] == 0.9

    def test_top_publisher_name_in_detail(self):
        result = detect_publisher_dominance(
            [{"name": "Bloomberg", "count": 15}],
            total_titles=20,
        )
        assert "Bloomberg" in result["detail"]
        assert "15/20" in result["detail"]

    def test_calibrated_medium_zone_recal_b1(self):
        # Recalibration B.1 (2026-06-10) : ratio 0.45 est entre MEDIUM=0.42 et
        # HIGH=0.50. Sous les anciens seuils (0.50/0.70) c'était "ok" ;
        # désormais "medium" (flag transparence, bias inchangé). Épingle la
        # nouvelle calibration pour éviter une régression silencieuse.
        result = detect_publisher_dominance(
            [{"name": "Reuters", "count": 9}],  # 9/20 = 0.45
            total_titles=20,
        )
        assert result["severity"] == "medium"
        assert result["score"] == 0.45

    def test_calibrated_high_majority_recal_b1(self):
        # Recalibration B.1 (2026-06-10) : ratio 0.55 > HIGH=0.50 = un éditeur
        # en majorité du cycle. Sous l'ancien HIGH=0.70 c'était "medium" ;
        # désormais "high" → le bias Google News est divisé par 2 en aval.
        result = detect_publisher_dominance(
            [{"name": "Reuters", "count": 11}],  # 11/20 = 0.55
            total_titles=20,
        )
        assert result["severity"] == "high"
        assert result["score"] == 0.55


class TestDetectVolumeSpike:
    def test_baseline_empty_returns_ok(self):
        result = detect_volume_spike(current_volume=100, baseline=[])
        assert result["type"] == "volume_spike"
        assert result["severity"] == "ok"
        assert "baseline insufficient" in result["detail"]

    def test_baseline_below_min_returns_ok(self):
        baseline = [50] * (VOLUME_SPIKE_MIN_BASELINE_POINTS - 1)
        result = detect_volume_spike(current_volume=200, baseline=baseline)
        assert result["severity"] == "ok"
        assert "baseline insufficient" in result["detail"]

    def test_baseline_all_invalid_returns_ok(self):
        baseline = [-1, -2, -3, 0, "abc", None, []] * 2  # tous invalides
        # Note: certains éléments comme 0, négatifs et non-numériques sont
        # filtrés. La liste finale après filtre = vide.
        result = detect_volume_spike(current_volume=100, baseline=baseline)
        assert result["severity"] == "ok"

    def test_baseline_all_zero_returns_ok(self):
        baseline = [0] * VOLUME_SPIKE_MIN_BASELINE_POINTS
        result = detect_volume_spike(current_volume=100, baseline=baseline)
        # 0 est filtré (`v > 0`), donc baseline finale = vide
        assert result["severity"] == "ok"

    def test_current_zero_returns_ok(self):
        baseline = [50] * VOLUME_SPIKE_MIN_BASELINE_POINTS
        result = detect_volume_spike(current_volume=0, baseline=baseline)
        assert result["severity"] == "ok"
        assert "current volume is zero" in result["detail"]

    def test_ratio_normal_is_ok(self):
        baseline = [50] * VOLUME_SPIKE_MIN_BASELINE_POINTS
        result = detect_volume_spike(current_volume=60, baseline=baseline)
        # ratio 1.2x = normal
        assert result["severity"] == "ok"
        assert result["score"] == 1.2

    def test_ratio_at_medium_threshold_is_medium(self):
        baseline = [10] * VOLUME_SPIKE_MIN_BASELINE_POINTS
        # Force ratio == VOLUME_SPIKE_THRESHOLD_MEDIUM (3.0)
        current = int(10 * VOLUME_SPIKE_THRESHOLD_MEDIUM)
        result = detect_volume_spike(current_volume=current, baseline=baseline)
        assert result["severity"] == "medium"
        assert result["score"] == 3.0

    def test_ratio_at_high_threshold_is_high(self):
        baseline = [10] * VOLUME_SPIKE_MIN_BASELINE_POINTS
        # Force ratio == VOLUME_SPIKE_THRESHOLD_HIGH (5.0)
        current = int(10 * VOLUME_SPIKE_THRESHOLD_HIGH)
        result = detect_volume_spike(current_volume=current, baseline=baseline)
        assert result["severity"] == "high"
        assert result["score"] == 5.0

    def test_ratio_extreme_is_high(self):
        baseline = [10] * VOLUME_SPIKE_MIN_BASELINE_POINTS
        result = detect_volume_spike(current_volume=200, baseline=baseline)
        # ratio 20x = très anormal
        assert result["severity"] == "high"
        assert result["score"] == 20.0

    def test_baseline_mixed_valid_invalid_uses_valid_only(self):
        baseline = [50, 60, 40, 0, -10, 70, 80, 90]  # 6 valides (50,60,40,70,80,90), 2 ignorés
        # mean = (50+60+40+70+80+90)/6 = 65
        # Mais len(baseline) >= MIN (7) donc activation OK
        result = detect_volume_spike(current_volume=200, baseline=baseline)
        # ratio = 200/65 = ~3.08 → medium
        assert result["severity"] == "medium"
        assert abs(result["score"] - 3.08) < 0.1

    def test_detail_contains_metrics(self):
        baseline = [50] * VOLUME_SPIKE_MIN_BASELINE_POINTS
        result = detect_volume_spike(current_volume=300, baseline=baseline)
        assert "300" in result["detail"]
        assert "50" in result["detail"]
        assert "×6.00" in result["detail"]


class TestDetectPublisherDiversitySpike:
    """Backlog #8 Option B. Le mode observation (défaut) force severity=ok ;
    les seuils ne s'appliquent que via observation_mode=False (post-calibration)."""

    def test_baseline_empty_returns_ok(self):
        result = detect_publisher_diversity_spike(current_distinct_publishers=20, baseline=[])
        assert result["type"] == "publisher_diversity_spike"
        assert result["severity"] == "ok"
        assert "baseline insufficient" in result["detail"]

    def test_baseline_below_min_returns_ok(self):
        baseline = [10] * (PUBLISHER_DIVERSITY_MIN_BASELINE_POINTS - 1)
        result = detect_publisher_diversity_spike(current_distinct_publishers=30, baseline=baseline)
        assert result["severity"] == "ok"
        assert "baseline insufficient" in result["detail"]

    def test_baseline_all_invalid_returns_ok(self):
        baseline = [-1, 0, "abc", None, [], -5, 0] * 2  # tous filtrés → vide
        result = detect_publisher_diversity_spike(current_distinct_publishers=20, baseline=baseline)
        assert result["severity"] == "ok"

    def test_current_zero_returns_ok(self):
        baseline = [10] * PUBLISHER_DIVERSITY_MIN_BASELINE_POINTS
        result = detect_publisher_diversity_spike(current_distinct_publishers=0, baseline=baseline)
        assert result["severity"] == "ok"
        assert "current distinct publishers is zero" in result["detail"]

    # --- Mode observation (défaut) : jamais d'action, mais métrique calculée ---

    def test_observation_mode_forces_ok_even_on_high_ratio(self):
        baseline = [10] * PUBLISHER_DIVERSITY_MIN_BASELINE_POINTS
        # ratio 4x = franchement au-dessus de high (2.0), mais observation → ok
        result = detect_publisher_diversity_spike(current_distinct_publishers=40, baseline=baseline)
        assert result["severity"] == "ok"
        assert result["score"] == 4.0  # la métrique reste exposée
        assert "[observation]" in result["detail"]

    def test_observation_mode_detail_contains_metrics(self):
        baseline = [10] * PUBLISHER_DIVERSITY_MIN_BASELINE_POINTS
        result = detect_publisher_diversity_spike(current_distinct_publishers=25, baseline=baseline)
        assert "25 distinct publishers" in result["detail"]
        assert "×2.50" in result["detail"]

    # --- Mode enforce (post-calibration) : les seuils s'appliquent ---

    def test_enforce_ratio_normal_is_ok(self):
        baseline = [10] * PUBLISHER_DIVERSITY_MIN_BASELINE_POINTS
        result = detect_publisher_diversity_spike(
            current_distinct_publishers=12, baseline=baseline, observation_mode=False
        )
        assert result["severity"] == "ok"
        assert result["score"] == 1.2
        assert "[observation]" not in result["detail"]

    def test_enforce_ratio_at_medium_threshold_is_medium(self):
        baseline = [10] * PUBLISHER_DIVERSITY_MIN_BASELINE_POINTS
        current = int(10 * PUBLISHER_DIVERSITY_SPIKE_THRESHOLD_MEDIUM)  # 15 → ratio 1.5
        result = detect_publisher_diversity_spike(
            current_distinct_publishers=current, baseline=baseline, observation_mode=False
        )
        assert result["severity"] == "medium"
        assert result["score"] == PUBLISHER_DIVERSITY_SPIKE_THRESHOLD_MEDIUM

    def test_enforce_ratio_at_high_threshold_is_high(self):
        baseline = [10] * PUBLISHER_DIVERSITY_MIN_BASELINE_POINTS
        current = int(10 * PUBLISHER_DIVERSITY_SPIKE_THRESHOLD_HIGH)  # 20 → ratio 2.0
        result = detect_publisher_diversity_spike(
            current_distinct_publishers=current, baseline=baseline, observation_mode=False
        )
        assert result["severity"] == "high"
        assert result["score"] == PUBLISHER_DIVERSITY_SPIKE_THRESHOLD_HIGH

    def test_enforce_baseline_mixed_valid_invalid_uses_valid_only(self):
        baseline = [10, 12, 8, 0, -3, 14, 16, 18]  # 6 valides (10,12,8,14,16,18), 2 ignorés
        # mean = (10+12+8+14+16+18)/6 = 13
        result = detect_publisher_diversity_spike(
            current_distinct_publishers=26, baseline=baseline, observation_mode=False
        )
        # ratio = 26/13 = 2.0 → high
        assert result["severity"] == "high"
        assert result["score"] == 2.0
