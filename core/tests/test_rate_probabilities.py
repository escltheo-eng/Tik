"""Tests des fonctions pures de RateProbabilitiesIngester (ADR-029).

Pas de pyfedwatch/Yahoo/FRED : l'import de FedWatch est lazy dans l'ingester, donc
les fonctions pures (parse symbole, hold/hike/cut, transformation du DataFrame) se
testent sans la dépendance. Le calcul réel pyfedwatch est validé en intégration live.
"""

import pandas as pd
import pytest

from tik_core.aggregator.rate_probabilities_ingester import (
    build_blob,
    parse_cme_symbol,
    summarize_meeting,
)


class TestParseCmeSymbol:
    def test_known(self):
        assert parse_cme_symbol("ZQN26") == (2026, 7)  # N = juillet
        assert parse_cme_symbol("ZQF26") == (2026, 1)  # F = janvier
        assert parse_cme_symbol("ZQZ27") == (2027, 12)  # Z = décembre
        assert parse_cme_symbol("ZQK26") == (2026, 5)  # K = mai (mois d'ancrage)

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_cme_symbol("XX26")
        with pytest.raises(ValueError):
            parse_cme_symbol("ZQ")


class TestSummarizeMeeting:
    def test_hold_hike_cut_split(self):
        row = {"3.25-3.50": 0.1, "3.50-3.75": 0.7, "3.75-4.00": 0.2}
        out = summarize_meeting(row, current_lower=3.5)
        assert out["hold"] == 0.7
        assert out["hike"] == 0.2  # range au-dessus du courant
        assert out["cut"] == 0.1  # range en-dessous
        assert out["most_likely_range"] == "3.50-3.75"
        assert out["most_likely_prob"] == 0.7

    def test_all_hold(self):
        out = summarize_meeting({"3.50-3.75": 1.0}, current_lower=3.5)
        assert out["hold"] == 1.0
        assert out["hike"] == 0.0
        assert out["cut"] == 0.0

    def test_ignores_unparseable_range(self):
        out = summarize_meeting({"bad": 0.5, "3.50-3.75": 0.5}, current_lower=3.5)
        assert out["hold"] == 0.5  # 'bad' ignoré, pas de crash


class TestBuildBlob:
    def _df(self):
        idx = pd.MultiIndex.from_tuples(
            [("2026-06-15", "2026-06-17"), ("2026-06-15", "2026-07-29")],
            names=["WatchDate", "FOMCDate"],
        )
        return pd.DataFrame(
            {
                "3.50-3.75": [0.989, 0.901],
                "3.75-4.00": [0.011, 0.098],
                "4.00-4.25": [0.0, 0.001],
            },
            index=idx,
        )

    def test_structure(self):
        blob = build_blob(self._df(), ll=3.5, ul=3.75, effr=3.62, watch_date="2026-06-15")
        assert blob["source"] == "pyfedwatch"
        assert blob["current_range"] == "3.50-3.75"
        assert blob["effr"] == 3.62
        assert blob["context_only"] is True
        assert len(blob["meetings"]) == 2

    def test_first_meeting(self):
        blob = build_blob(self._df(), ll=3.5, ul=3.75, effr=3.62, watch_date="2026-06-15")
        m0 = blob["meetings"][0]
        assert m0["date"] == "2026-06-17"
        assert m0["hold"] == 0.989
        assert m0["hike"] == 0.011
        assert m0["cut"] == 0.0
        assert m0["most_likely_range"] == "3.50-3.75"
        assert m0["most_likely_prob"] == 0.989
        # proba négligeable (4.00-4.25 = 0.0) exclue de l'affichage
        assert "4.00-4.25" not in m0["probabilities"]
        assert m0["probabilities"]["3.50-3.75"] == 0.989

    def test_probabilities_sum_to_one(self):
        blob = build_blob(self._df(), ll=3.5, ul=3.75, effr=3.62, watch_date="2026-06-15")
        for m in blob["meetings"]:
            assert abs(m["hold"] + m["hike"] + m["cut"] - 1.0) < 0.01
