"""Mesure la distribution réelle dispersion → veracity (ADR-026, Lot 2) — lecture seule.

Contexte
--------
ADR-026 a diagnostiqué que la veracity des shorts BTC swing sature à 0.70 parce
que la dispersion des sources inclut l'outlier Fear & Greed (exclu, lui, de la
direction et du circuit breaker). Plutôt que tuner `_veracity_from_dispersion`
à l'aveugle, on a instrumenté chaque cycle avec un log `veracity.shadow`
(cf. `cross_validator.veracity_shadow_fields`). Ce script LIT ces logs et
calcule la distribution réelle de la dispersion + ce que la veracity DONNERAIT
sous trois variantes, pour pouvoir trancher empiriquement (méthode B.1).

Il n'écrit RIEN, ne touche ni au pipeline ni à la base. Mesurer ≠ agir.

Trois variantes comparées (par signal, recomputées via la VRAIE cross_validate)
-----------------------------------------------------------------------------
- **V0 actuel**   : `stdev(tous les biais)` → veracity live (ce qui tourne).
- **V1 pstdev**   : `pstdev(tous les biais)` → corrige l'incohérence d'estimateur
  A5 (la branche N=2 utilise déjà pstdev). N'exclut pas l'outlier.
- **V2 hors-outlier** : `pstdev(biais valides, outlier exclu)` → option A1
  (cohérent avec direction + circuit breaker). Remonte les shorts vers ~0.95.

Usage
-----
    docker logs tik-scheduler 2>&1 | grep 'veracity.shadow' \\
        | docker exec -i tik-core python -m tik_core.scripts.measure_veracity_dispersion

    # ou filtrer une entité/horizon :
    ... | python -m tik_core.scripts.measure_veracity_dispersion --entity BTC --horizon swing

Limites assumées
----------------
1. Accumulation depuis le déploiement du Lot 2 (2026-06-10) → ré-évaluer après
   ≥ 2 semaines ET idéalement un changement de régime FG (sortie de peur extrême).
2. Recompute V1/V2 via `cross_validate` sur les `biases_json` loggués = fidèle,
   mais dépend de l'algo d'outlier courant (si on le change, re-mesurer).
3. Décision sémantique include/exclude outlier = ADR-026-bis, PAS automatique :
   ce script éclaire, il ne tranche pas (Axe #1 : veracity ≠ edge — cf. GOLD 0.89
   pour 4.8 % de hit).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys

from tik_core.scoring.cross_validator import cross_validate
from tik_core.scoring.swing_engine import _veracity_from_dispersion

_DISP_RE = re.compile(r"dispersion=([0-9.]+)")
_VERAC_RE = re.compile(r"veracity=([0-9.]+)")
_ENTITY_RE = re.compile(r"entity_id=([A-Za-z]+)")
_HORIZON_RE = re.compile(r"horizon=([a-z]+)")
# structlog console entoure les valeurs string contenant des espaces de
# guillemets (simples le plus souvent) → on les rend optionnels.
_BIASES_RE = re.compile(r"biases_json=[\"']?(\{[^}]*\})")


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def parse_lines(lines: list[str]) -> list[dict]:
    rows: list[dict] = []
    for line in lines:
        if "veracity.shadow" not in line:
            continue
        m_d = _DISP_RE.search(line)
        m_v = _VERAC_RE.search(line)
        m_e = _ENTITY_RE.search(line)
        m_h = _HORIZON_RE.search(line)
        m_b = _BIASES_RE.search(line)
        if not (m_d and m_v and m_b):
            continue
        try:
            biases = json.loads(m_b.group(1))
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "dispersion": float(m_d.group(1)),
                "veracity": float(m_v.group(1)),
                "entity": m_e.group(1) if m_e else "?",
                "horizon": m_h.group(1) if m_h else "?",
                "biases": {k: float(v) for k, v in biases.items()},
            }
        )
    return rows


def _variant_veracities(biases: dict[str, float]) -> tuple[float, float, float]:
    """(V0 stdev-all, V1 pstdev-all, V2 pstdev-valid) via la vraie cross_validate."""
    values = list(biases.values())
    if len(values) < 2:
        v = _veracity_from_dispersion(0.0)
        return v, v, v
    cv = cross_validate(biases)
    valid = [b for s, b in biases.items() if s not in cv.outlier_sources]
    v0 = _veracity_from_dispersion(statistics.stdev(values))
    v1 = _veracity_from_dispersion(statistics.pstdev(values))
    v2 = _veracity_from_dispersion(statistics.pstdev(valid) if len(valid) >= 2 else 0.0)
    return v0, v1, v2


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="fichier de logs (défaut: stdin)")
    ap.add_argument("--entity", default=None)
    ap.add_argument("--horizon", default=None)
    args = ap.parse_args(argv[1:])

    lines = open(args.path, encoding="utf-8").readlines() if args.path else sys.stdin.readlines()
    rows = parse_lines(lines)
    if args.entity:
        rows = [r for r in rows if r["entity"] == args.entity]
    if args.horizon:
        rows = [r for r in rows if r["horizon"] == args.horizon]

    print("=" * 76)
    print("  MESURE dispersion → veracity (ADR-026 Lot 2) — lecture seule")
    print("=" * 76)
    filt = f" entity={args.entity or 'tous'} horizon={args.horizon or 'tous'}"
    print(f"\nLignes veracity.shadow retenues :{filt} → {len(rows)}")
    if not rows:
        print("  (aucune donnée — le Lot 2 vient peut-être d'être déployé ; ré-essayer plus tard)")
        return 0

    disp = [r["dispersion"] for r in rows]
    print(f"\n[dispersion] min/méd/moy/max = {min(disp):.3f} / {statistics.median(disp):.3f} / "
          f"{statistics.mean(disp):.3f} / {max(disp):.3f}")
    for p in (50, 75, 90, 95, 99):
        print(f"  p{p:<2} = {_percentile(disp, p):.3f}")

    # Distribution des veracities sous les 3 variantes
    from collections import Counter

    v0c, v1c, v2c = Counter(), Counter(), Counter()
    for r in rows:
        v0, v1, v2 = _variant_veracities(r["biases"])
        v0c[v0] += 1
        v1c[v1] += 1
        v2c[v2] += 1

    def show(name: str, c: Counter) -> None:
        tot = sum(c.values())
        dist = "  ".join(f"{k}:{v}({100 * v / tot:.0f}%)" for k, v in sorted(c.items()))
        print(f"  {name:<28} {dist}")

    print("\n[veracity par variante]")
    show("V0 actuel (stdev all)", v0c)
    show("V1 pstdev all (fix A5)", v1c)
    show("V2 pstdev hors-outlier (A1)", v2c)
    print("\n⚠ Éclaire la décision, ne tranche PAS (veracity ≠ edge — Axe #1, cf. ADR-026).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
