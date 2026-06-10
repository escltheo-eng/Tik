"""Mesure des seuils du détecteur d'anomalies P6 — lecture seule (backlog 7.B.1).

Contexte
--------
Les seuils de `scoring/anomaly_detector.py` ont été posés « au pifomètre
raisonné » (CLAUDE.md décision D-P6-4) puis devaient être recalibrés post-J+30
sur dataset réel (backlog 7.B.1). Ce script reconstruit la distribution RÉELLE
du ratio de chaque détecteur à partir des logs de production et propose des
seuils alignés sur les percentiles 90 (MEDIUM) et ~99 (HIGH).

Il n'écrit RIEN et ne touche ni au pipeline ni à la base. Mesurer ≠ agir.

Réalité au 2026-06-10 (1re recalibration)
------------------------------------------
Sur les 3 seuils visés par B.1, un seul est calibrable faute de données :

  * `brigading_reddit`     → Reddit IP-banni (Bug 11) : 0 cycle publié. INCALIBRABLE.
  * `volume_spike`         → dormant (plus câblé à aucun ingester).       INCALIBRABLE.
  * `publisher_dominance`  → Google News tourne : ~95 cycles/jour.        CALIBRABLE.

Donc ce script se concentre sur `publisher_dominance` (Google News). Quand
Reddit reviendra, le même squelette resservira pour `brigading_reddit` en
changeant la regex de l'event loggué.

Source de données
-----------------
Le champ `anomaly_score` de la ligne `google_news.published` EST exactement le
ratio comparé au seuil en prod (cf. `google_news_ingester._run`), loggué à
CHAQUE cycle quelle que soit la sévérité → la distribution complète est fidèle
(pas seulement les cas anormaux). On lit donc ces lignes plutôt que de
reconstruire depuis la table `headlines` (qui est dédupliquée → ratio biaisé).

Usage
-----
Le script lit les lignes sur STDIN (ou un fichier en 1er argument). Le caller
fournit les logs ; côté VPS :

    docker logs tik-ingesters 2>&1 | grep 'google_news.published' \\
        | python -m tik_core.scripts.measure_anomaly_thresholds

ou, depuis un export :

    python -m tik_core.scripts.measure_anomaly_thresholds /tmp/gn_published.log

Limites assumées
----------------
1. Les logs Docker json-file ne remontent qu'à la création du conteneur
   (~16 j au 2026-06-10), < 30 j cible de la méthodo backlog.
2. Régime de marché unique sur la fenêtre (bear) → la distribution peut bouger.
3. Aucun event de manipulation éditoriale CONFIRMÉ dans la fenêtre : on calibre
   la queue « normale », pas une vérité-terrain d'anomalie réelle.
"""

from __future__ import annotations

import re
import sys
from statistics import mean, median

# Seuils actuels (importés pour comparer mesure vs config en place).
from tik_core.scoring.anomaly_detector import (
    PUBLISHER_DOMINANCE_THRESHOLD_HIGH,
    PUBLISHER_DOMINANCE_THRESHOLD_MEDIUM,
)

_SCORE_RE = re.compile(r"anomaly_score=([0-9.]+)")
_SEV_RE = re.compile(r"anomaly_severity=(\w+)")
_ENTITY_RE = re.compile(r"entity_id=(\w+)")


def _percentile(values: list[float], p: float) -> float:
    """Percentile par interpolation linéaire (même définition que numpy 'linear')."""
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def parse_lines(lines: list[str]) -> list[dict]:
    """Extrait (score, severity, entity) des lignes google_news.published.

    Les lignes sans les 3 champs sont ignorées silencieusement.
    """
    rows: list[dict] = []
    for line in lines:
        m_s = _SCORE_RE.search(line)
        m_sev = _SEV_RE.search(line)
        m_e = _ENTITY_RE.search(line)
        if not (m_s and m_sev and m_e):
            continue
        rows.append(
            {
                "score": float(m_s.group(1)),
                "severity": m_sev.group(1),
                "entity": m_e.group(1),
            }
        )
    return rows


def _report_group(label: str, scores: list[float]) -> None:
    if not scores:
        print(f"\n[{label}] aucun échantillon")
        return
    print(f"\n[{label}] N={len(scores)}")
    print(
        f"  min/médiane/moy/max : {min(scores):.3f} / {median(scores):.3f} / "
        f"{mean(scores):.3f} / {max(scores):.3f}"
    )
    for p in (50, 75, 90, 95, 99):
        print(f"  p{p:<2} = {_percentile(scores, p):.3f}")
    n_med = sum(1 for v in scores if PUBLISHER_DOMINANCE_THRESHOLD_MEDIUM <= v < PUBLISHER_DOMINANCE_THRESHOLD_HIGH)
    n_high = sum(1 for v in scores if v >= PUBLISHER_DOMINANCE_THRESHOLD_HIGH)
    total = len(scores)
    print(
        f"  >= MEDIUM ({PUBLISHER_DOMINANCE_THRESHOLD_MEDIUM}) : "
        f"{n_med + n_high} ({100 * (n_med + n_high) / total:.1f}%)"
    )
    print(
        f"  >= HIGH   ({PUBLISHER_DOMINANCE_THRESHOLD_HIGH}) : "
        f"{n_high} ({100 * n_high / total:.1f}%)"
    )


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        with open(argv[1], encoding="utf-8") as f:
            lines = f.readlines()
    else:
        lines = sys.stdin.readlines()

    rows = parse_lines(lines)
    print("=" * 76)
    print("  MESURE SEUILS publisher_dominance (Google News) — lecture seule")
    print("=" * 76)
    print(f"\nLignes google_news.published parsées : {len(rows)}")

    # score == 0.0 = early-return (titres insuffisants / pas de publisher) → non mesuré.
    measured = [r for r in rows if r["score"] > 0.0]
    print(f"  dont ratio réel mesuré (score>0)     : {len(measured)}")
    print(f"  dont non mesuré (score==0)           : {len(rows) - len(measured)}")

    print(f"\nSeuils en place : MEDIUM={PUBLISHER_DOMINANCE_THRESHOLD_MEDIUM} "
          f"HIGH={PUBLISHER_DOMINANCE_THRESHOLD_HIGH}")

    _report_group("TOUS (pooled)", [r["score"] for r in measured])
    for ent in sorted({r["entity"] for r in measured}):
        _report_group(ent, [r["score"] for r in measured if r["entity"] == ent])

    # Recommandation : un seuil GLOBAL doit être calibré sur l'entité la PLUS
    # concentrée (contrainte haute), sinon il sur-flague celle-ci. On prend donc
    # le p90/p99 max parmi les entités (= BTC en pratique ; GOLD est plus diffus).
    entities = sorted({r["entity"] for r in measured})
    if entities:
        p90_by_ent = {e: _percentile([r["score"] for r in measured if r["entity"] == e], 90) for e in entities}
        p99_by_ent = {e: _percentile([r["score"] for r in measured if r["entity"] == e], 99) for e in entities}
        binding = max(p90_by_ent, key=p90_by_ent.get)
        reco_medium = round(p90_by_ent[binding], 2)
        reco_high = max(0.50, round(p99_by_ent[binding], 2))
        print("\n--- RECOMMANDATION (méthodo backlog : MEDIUM≈p90, HIGH≈p99/majorité) ---")
        print(f"  entité contraignante (p90 max) : {binding}")
        print(f"  MEDIUM ≈ p90 {binding}        → {reco_medium}")
        print(f"  HIGH   ≈ max(0.50, p99 {binding}) → {reco_high}")
        print("  ⚠ À pondérer par les limites (cf. docstring) : fenêtre < 30 j,")
        print("    régime unique, aucune anomalie confirmée comme vérité-terrain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
