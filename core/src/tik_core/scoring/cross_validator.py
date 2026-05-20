"""Cross-validation runtime des biais sources sentiment (anti fake-news).

Détecte les sources outliers au moment de l'émission d'un signal et
adapte le `circuit_breaker_status` du signal en conséquence.

Algorithme adapté à la taille de l'échantillon (N petit en pratique : 2-5
sources sentiment par décision) :

- N ≤ 1 : pas d'outlier détectable, status "ok".
- N = 2 : règle de disagreement (signes opposés ET écart > seuil) → status
  "degraded" mais aucune source individuelle marquée outlier (on ne peut
  pas dire qui ment).
- N ≥ 3 : combinaison de deux mécanismes complémentaires :
  1. **Modified Z-score d'Iglewicz-Hoaglin** (1993) sur les valeurs
     individuelles, formule `0.6745 × (x - median) / MAD`, seuil 3.5.
     Fallback seuil absolu (`|x - median| > 0.3`) quand MAD = 0 (cas où
     ≥50 % des valeurs sont identiques).
  2. **Détection de dispersion globale** par écart-type. Indépendante
     de la détection individuelle, elle capture les cas où aucun point
     n'est statistiquement outlier mais la distribution est globalement
     éclatée (ex: 2 sources +0.5, 2 sources -0.5 → Modified Z voit deux
     groupes "normaux", mais c'est un disagreement majeur à flagger).

  Le `circuit_breaker_status` final est le **pire des deux** (max
  sévérité entre détection individuelle et dispersion globale).

Les outliers détectés sont **neutralisés** dans la moyenne combinée
(retirés du calcul). Le status est :

- "ok" : 0 outlier
- "degraded" : ratio outliers ≥ 50%
- "tripped" : ratio outliers ≥ 75%

Ce module est volontairement pure-logic : pas de dépendance à
SwingDecision/FlashDecision (duck typing dans
`apply_cross_validation_to_decision`).

Voir docs/adr/011-anti-fake-news.md pour le contexte architectural.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CrossValidationResult:
    """Résultat de la cross-validation des biais sources."""

    combined_bias: float  # Moyenne des biais valides (outliers exclus)
    circuit_breaker_status: str  # "ok" | "degraded" | "tripped"
    outlier_sources: set[str] = field(default_factory=set)
    n_sources: int = 0
    method: str = "no_op"  # "no_op" | "disagreement_n2" | "modified_zscore" | "zero_mad_fallback"
    dispersion: float = 0.0  # std des biais (audit de la dispersion globale)


# ----- Helpers stat -----


def compute_mad(values: list[float]) -> float:
    """Median Absolute Deviation : médiane des |x - médiane|.

    Estimateur de dispersion robuste aux outliers (contrairement à std qui
    est elle-même polluée par les outliers — tautologie).
    """
    if not values:
        return 0.0
    med = statistics.median(values)
    deviations = [abs(v - med) for v in values]
    return statistics.median(deviations)


def detect_outliers_modified_zscore(
    biases: dict[str, float],
    threshold: float = 3.5,
    zero_mad_abs_threshold: float = 0.3,
) -> set[str]:
    """Modified Z-score d'Iglewicz-Hoaglin (1993).

    Formule : `modified_z = 0.6745 × (x - median) / MAD`
    Seuil typique : 3.5 (Iglewicz & Hoaglin, "How to Detect and Handle Outliers", 1993).

    Si MAD = 0 (≥50 % des valeurs identiques), fallback seuil absolu
    (cf. `_detect_outliers_zero_mad`).
    """
    if len(biases) < 3:
        return set()

    values = list(biases.values())
    med = statistics.median(values)
    mad = compute_mad(values)

    if mad == 0:
        return _detect_outliers_zero_mad(biases, abs_threshold=zero_mad_abs_threshold)

    outliers: set[str] = set()
    for source, value in biases.items():
        modified_z = 0.6745 * (value - med) / mad
        if abs(modified_z) > threshold:
            outliers.add(source)
    return outliers


def _detect_outliers_zero_mad(
    biases: dict[str, float],
    abs_threshold: float = 0.3,
) -> set[str]:
    """Fallback quand MAD = 0 (≥50 % des valeurs identiques).

    Dans ce cas la médiane représente la valeur dominante par construction
    (la "norme" du groupe). Toute valeur dont l'écart à la médiane dépasse
    un seuil absolu est outlier.

    Le seuil par défaut 0.3 est calibré pour les biais sentiment Tik qui
    sont **par construction bornés dans [-1, +1]** : un écart > 0.3 à la
    valeur dominante (≥30 % de l'amplitude max) signale sans ambiguïté un
    désaccord. Ce fallback est plus robuste que Tukey's fence (IQR) sur
    petits échantillons skewed.
    """
    if len(biases) < 3:
        return set()
    med = statistics.median(biases.values())
    return {source for source, v in biases.items() if abs(v - med) > abs_threshold}


def detect_global_dispersion(
    values: list[float],
    degraded_std: float = 0.5,
    tripped_std: float = 0.85,
) -> str:
    """Mesure la dispersion globale via écart-type, indépendante des outliers.

    Sur des biais bornés `[-1, +1]`, l'écart-type max théorique est ~1.0
    (N=2 aux extrêmes ±1) ou ~1.15 (N≥4 split 50/50). Les seuils par
    défaut sont calibrés sur cette échelle :

    - std ≥ 0.85 → "tripped" (dispersion proche du max → désaccord majeur)
    - std ≥ 0.50 → "degraded" (dispersion notable, pas de consensus)
    - std < 0.50 → "ok" (concordance raisonnable)

    Capture les distributions bimodales (50/50) que Modified Z-score
    laisse passer car aucun point individuel n'est statistiquement isolé.
    """
    if len(values) < 3:
        return "ok"
    sigma = statistics.stdev(values)
    if sigma >= tripped_std:
        return "tripped"
    if sigma >= degraded_std:
        return "degraded"
    return "ok"


def detect_disagreement_n2(biases: dict[str, float], threshold: float = 0.8) -> bool:
    """Disagreement notable entre 2 sources : signes opposés ET écart > seuil.

    Avec N=2, on ne peut pas désigner statistiquement qui est outlier. Mais
    on peut flagger le fait que les sources divergent fortement, ce qui
    suffit à dégrader le `circuit_breaker_status`.
    """
    if len(biases) != 2:
        return False
    a, b = list(biases.values())
    return (a * b < 0) and (abs(a - b) > threshold)


# ----- API principale -----


def cross_validate(
    biases: dict[str, float],
    *,
    zscore_threshold: float = 3.5,
    disagreement_threshold: float = 0.8,
    degraded_ratio: float = 0.5,
    tripped_ratio: float = 0.75,
) -> CrossValidationResult:
    """Cross-valide un dict {source_name: bias_in_[-1,+1]}.

    Logique adaptée à la taille de l'échantillon (cf. docstring du module).

    Retourne un CrossValidationResult avec :
    - `combined_bias` : moyenne des biais valides (outliers retirés)
    - `circuit_breaker_status` : "ok" / "degraded" / "tripped"
    - `outlier_sources` : ensemble des sources détectées outlier
    - `method` : algorithme effectivement utilisé (debug/audit)
    """
    n = len(biases)

    if n == 0:
        return CrossValidationResult(
            combined_bias=0.0,
            circuit_breaker_status="ok",
            n_sources=0,
            method="no_op",
        )

    if n == 1:
        return CrossValidationResult(
            combined_bias=next(iter(biases.values())),
            circuit_breaker_status="ok",
            n_sources=1,
            method="no_op",
        )

    if n == 2:
        combined = sum(biases.values()) / 2
        values = list(biases.values())
        # Dispersion via pstdev (population std) car on a une "population"
        # complète de 2 sources, pas un échantillon estimant une population
        # plus grande. Sur biais bornés [-1, +1] : pstdev([+1, -1]) = 1.0 (max),
        # pstdev([+0.5, -0.5]) = 0.5, pstdev([+0.5, +0.5]) = 0. Cohérent avec
        # les paliers 0.2/0.4/0.6/0.8 de `_veracity_from_dispersion` dans les
        # engines swing/flash. Résout un bug structurel post-Paquet 18 où
        # dispersion restait à 0.0 (default dataclass) → veracity figée 0.95
        # sur tous les signaux N=2 (100 % flash BTC, 100 % swing GOLD
        # post-Paquet 19, ~99.5 % swing BTC quand des ingesters sont down).
        dispersion = statistics.pstdev(values)
        if detect_disagreement_n2(biases, threshold=disagreement_threshold):
            return CrossValidationResult(
                combined_bias=combined,
                circuit_breaker_status="degraded",
                n_sources=2,
                method="disagreement_n2",
                dispersion=dispersion,
            )
        return CrossValidationResult(
            combined_bias=combined,
            circuit_breaker_status="ok",
            n_sources=2,
            method="disagreement_n2",
            dispersion=dispersion,
        )

    # N ≥ 3 : Modified Z-score (outliers individuels) + dispersion globale (std)
    values = list(biases.values())
    mad = compute_mad(values)
    method = "modified_zscore" if mad > 0 else "zero_mad_fallback"
    outliers = detect_outliers_modified_zscore(biases, threshold=zscore_threshold)

    valid_biases = [v for src, v in biases.items() if src not in outliers]
    combined = sum(valid_biases) / len(valid_biases) if valid_biases else statistics.median(values)

    # Status par ratio d'outliers individuels
    ratio = len(outliers) / n
    if ratio >= tripped_ratio:
        status_outliers = "tripped"
    elif ratio >= degraded_ratio:
        status_outliers = "degraded"
    else:
        status_outliers = "ok"

    # Status par dispersion globale, calculée SUR LES NON-OUTLIERS uniquement
    # pour éviter le double comptage (un outlier extrême déjà flaggé individuellement
    # ne doit pas re-pénaliser via la dispersion). Capture le 50/50 split que
    # Modified Z laisse passer.
    status_dispersion = detect_global_dispersion(valid_biases) if len(valid_biases) >= 3 else "ok"

    # Status final = pire des deux
    severity = {"ok": 0, "degraded": 1, "tripped": 2}
    status = (
        status_outliers
        if severity[status_outliers] >= severity[status_dispersion]
        else status_dispersion
    )

    # Dispersion brute (toutes valeurs) — pour audit, pas pour la décision
    dispersion = statistics.stdev(values) if len(values) >= 2 else 0.0

    return CrossValidationResult(
        combined_bias=combined,
        circuit_breaker_status=status,
        outlier_sources=outliers,
        n_sources=n,
        method=method,
        dispersion=dispersion,
    )


# ----- Intégration côté engine (duck typing decision) -----


def apply_cross_validation_to_decision(
    decision,
    biases: dict[str, float],
    *,
    mode: Literal["active", "shadow"] = "active",
) -> CrossValidationResult:
    """Applique la cross-validation à une décision (en place, selon mode).

    `decision` doit exposer les attributs : `direction`, `hypothesis`,
    `evidence` (list[dict]), `circuit_breaker_status` (str). Compatible
    avec SwingDecision et FlashDecision sans coupling explicite.

    En mode "active" :
    - met à jour `decision.circuit_breaker_status`
    - marque chaque evidence outlier avec `is_outlier=True`
    - si "tripped" : force `direction="neutral"`, préfixe `hypothesis`

    En mode "shadow" :
    - decision est inchangée (pure observation)
    - le résultat est retourné pour log/audit côté caller

    Retourne le CrossValidationResult dans les deux modes.
    """
    cv = cross_validate(biases)

    if mode == "active":
        decision.circuit_breaker_status = cv.circuit_breaker_status
        if cv.outlier_sources:
            for ev in decision.evidence:
                if ev.get("source") in cv.outlier_sources:
                    ev["is_outlier"] = True
        if cv.circuit_breaker_status == "tripped":
            original = decision.hypothesis
            decision.direction = "neutral"
            decision.hypothesis = (
                f"Anti fake-news: {len(cv.outlier_sources)}/{cv.n_sources} "
                f"sources flagged as outliers — direction forced to neutral. "
                f"(Original: {original})"
            )

    return cv
