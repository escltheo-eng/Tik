"""Anomaly detector — couche qualité upstream par ingester (P6 plan fiabilité).

Complémentaire à l'anti fake-news ADR-011 qui agit en aval sur le biais
agrégé après cross-validation. Ce module détecte 3 patterns suspects au
niveau de chaque ingester individuel, AVANT que la donnée n'arrive dans
le scoring engine :

1. **Brigading Reddit** : ratio comments/upvotes anormalement élevé sur
   les posts agrégés (suggère manipulation coordonnée par bots ou
   controverse organisée).

2. **Dominance publisher Google News** : un seul publisher représente
   plus de la moitié des titres du cycle (suggère cycle éditorialement
   biaisé).

3. **Pic diversité éditeurs CryptoCompare** : nombre d'éditeurs distincts
   couvrant l'actif sur le cycle, anormalement élevé vs baseline 7 jours
   (suggère un événement majeur — approbation ETF, hack, décision
   réglementaire — où beaucoup d'outlets couvrent la même story).
   Remplace l'ancienne détection de pic de *volume* brut, dormante car
   l'API CryptoCompare renvoie ~50 articles par défaut (volume quasi
   constant). Le détecteur de volume `detect_volume_spike` reste fourni
   ici comme helper générique mais n'est plus câblé sur un ingester.
   Cf. backlog #8 (Option B). Livré en **mode observation** d'abord :
   la métrique est calculée et loguée, mais severity reste "ok" (aucune
   pondération du bias) tant que la corrélation pic ↔ événement n'a pas
   été validée empiriquement (cf. `PUBLISHER_DIVERSITY_OBSERVATION_MODE`).

Architecture (cf. CLAUDE.md Paquet 21 P6 décision D-P6-2) :

- Helpers purs ici. Pas d'accès Redis ni HTTP.
- Chaque ingester appelle son détecteur après avoir collecté son cycle,
  AVANT publish Redis. Le résultat est ajouté au payload sous la clé
  `anomaly`.
- L'engine swing consomme `anomaly` dans `_enrich_with_<source>` et
  applique la pondération :
    severity=high   → bias divisé par 2 (réduit l'influence sans supprimer)
    severity=medium → bias inchangé + flag dans evidence pour transparence
    severity=ok     → bias normal

Seuils calibrés au pifomètre raisonné (cf. CLAUDE.md décision D-P6-4),
à recalibrer empiriquement post-J+30 sur dataset réel.
"""

from __future__ import annotations

from typing import Literal, TypedDict

Severity = Literal["ok", "medium", "high"]


class AnomalyResult(TypedDict):
    """Résultat structuré d'une détection d'anomalie sur un cycle ingester.

    Attributes:
        type: identifiant du type d'anomalie (brigading_reddit,
            publisher_dominance, volume_spike).
        score: valeur brute de la métrique (ratio, %, etc.) — informatif.
        severity: ok / medium / high. Consommé par l'engine pour décider
            la pondération du bias.
        detail: explication humaine, persistée pour audit + dashboard.
    """

    type: str
    score: float
    severity: Severity
    detail: str


# ----- Seuils (pifomètre raisonné, cf. CLAUDE.md décision D-P6-4) -----

# Brigading Reddit : ratio comments / upvotes par post agrégé.
# Hypothèse de base : un post sain a en moyenne 0.1-0.3 commentaire par
# upvote (typique sur r/Bitcoin / r/CryptoMarkets). Un ratio > 1.0 est
# franchement suspect (autant de discussion que de vote = controverse
# organisée ou bots qui commentent en chaîne).
BRIGADING_THRESHOLD_HIGH = 1.0
BRIGADING_THRESHOLD_MEDIUM = 0.5
BRIGADING_MIN_POSTS = 3  # < 3 posts = échantillon trop petit, severity=ok

# Dominance publisher Google News : ratio top_publisher / total titres.
# Validation Paquet 4 Session 1 a observé Yahoo Finance à 40 % des hits
# sur certains cycles BTC = déjà élevé. > 50 % = vraiment dominé.
PUBLISHER_DOMINANCE_THRESHOLD_HIGH = 0.70
PUBLISHER_DOMINANCE_THRESHOLD_MEDIUM = 0.50
PUBLISHER_DOMINANCE_MIN_TITLES = 5  # < 5 titres = pas assez pour juger

# Pic volume CryptoCompare : ratio volume_today / mean(baseline_7d).
# > 3x = pic anormal (vrai event majeur OU campagne PR), > 5x = très anormal.
# Note : un vrai event macro peut générer un pic légitime → severity=medium
# ne supprime pas le bias, juste le flag dans evidence pour transparence.
VOLUME_SPIKE_THRESHOLD_HIGH = 5.0
VOLUME_SPIKE_THRESHOLD_MEDIUM = 3.0
VOLUME_SPIKE_MIN_BASELINE_POINTS = 7  # baseline insuffisante = severity=ok

# Pic diversité éditeurs CryptoCompare : ratio nb_éditeurs_distincts_today /
# mean(baseline_7d). Contrairement au volume brut (toujours ~50 articles via
# l'API CC → dormant), le nombre d'éditeurs distincts varie : un pic signale
# que beaucoup d'outlets couvrent simultanément l'actif (event majeur).
# Seuils pifomètre raisonné, À CALIBRER après la phase d'observation (cf.
# backlog #8). Bornés bas car le nombre d'éditeurs est plafonné par l'univers
# fini de publishers CC (~30-40) et par les ~50 articles du cycle.
PUBLISHER_DIVERSITY_SPIKE_THRESHOLD_HIGH = 2.0
PUBLISHER_DIVERSITY_SPIKE_THRESHOLD_MEDIUM = 1.5
PUBLISHER_DIVERSITY_MIN_BASELINE_POINTS = 7  # baseline insuffisante = severity=ok

# Mode observation : tant que True, `detect_publisher_diversity_spike` calcule
# et expose le ratio dans `detail` mais force severity="ok" (zéro pondération
# du bias). Permet de mesurer la corrélation pic ↔ événement sur plusieurs
# semaines AVANT d'activer le flag (cf. backlog #8 « valider empiriquement
# avant de coder dur » + garde-fou trading manuel actif). Passer à False après
# calibration pour activer la sévérité.
PUBLISHER_DIVERSITY_OBSERVATION_MODE = True


# ----- Helpers de détection -----


def detect_brigading_reddit(posts: list[dict]) -> AnomalyResult:
    """Détecte un brigading sur la base du ratio agrégé comments/upvotes.

    Pour chaque post fourni, lit `num_comments` et `score` (upvotes Reddit).
    Calcule le ratio total `sum(comments) / sum(upvotes)` plutôt qu'une
    moyenne des ratios individuels — un post viral à 10000 upvotes pèse
    naturellement plus dans cette moyenne, ce qui est l'effet souhaité
    (un brigading touche typiquement des posts qui montent vite).

    Args:
        posts: list de dict avec au minimum `score` (int upvotes) et
            `num_comments` (int). Posts invalides (champs manquants ou
            non numériques) sont ignorés silencieusement.

    Returns:
        AnomalyResult.
    """
    if len(posts) < BRIGADING_MIN_POSTS:
        return AnomalyResult(
            type="brigading_reddit",
            score=0.0,
            severity="ok",
            detail=f"insufficient sample ({len(posts)} posts < {BRIGADING_MIN_POSTS})",
        )

    total_upvotes = 0
    total_comments = 0
    n_valid = 0
    for post in posts:
        try:
            upvotes = int(post.get("score", 0))
            comments = int(post.get("num_comments", 0))
        except (TypeError, ValueError):
            continue
        if upvotes <= 0:
            continue
        total_upvotes += upvotes
        total_comments += comments
        n_valid += 1

    if total_upvotes <= 0 or n_valid < BRIGADING_MIN_POSTS:
        return AnomalyResult(
            type="brigading_reddit",
            score=0.0,
            severity="ok",
            detail=f"insufficient valid posts after filter ({n_valid})",
        )

    ratio = total_comments / total_upvotes

    if ratio >= BRIGADING_THRESHOLD_HIGH:
        severity: Severity = "high"
    elif ratio >= BRIGADING_THRESHOLD_MEDIUM:
        severity = "medium"
    else:
        severity = "ok"

    return AnomalyResult(
        type="brigading_reddit",
        score=round(ratio, 3),
        severity=severity,
        detail=(
            f"comments/upvotes ratio {ratio:.2f} on {n_valid} posts "
            f"(total {total_comments} comments / {total_upvotes} upvotes)"
        ),
    )


def detect_publisher_dominance(
    top_publishers: list[dict],
    total_titles: int,
) -> AnomalyResult:
    """Détecte une dominance excessive d'un seul publisher dans Google News.

    Args:
        top_publishers: list de {"name": str, "count": int} triée DESC,
            comme produit par `Counter.most_common()` côté ingester.
        total_titles: nombre total de titres du cycle (avant agrégation).

    Returns:
        AnomalyResult.
    """
    if total_titles < PUBLISHER_DOMINANCE_MIN_TITLES:
        return AnomalyResult(
            type="publisher_dominance",
            score=0.0,
            severity="ok",
            detail=f"insufficient titles ({total_titles} < {PUBLISHER_DOMINANCE_MIN_TITLES})",
        )

    if not top_publishers:
        return AnomalyResult(
            type="publisher_dominance",
            score=0.0,
            severity="ok",
            detail="no publishers data",
        )

    try:
        top = top_publishers[0]
        top_name = str(top.get("name", "unknown"))
        top_count = int(top.get("count", 0))
    except (KeyError, TypeError, ValueError):
        return AnomalyResult(
            type="publisher_dominance",
            score=0.0,
            severity="ok",
            detail="malformed top_publishers data",
        )

    if top_count <= 0:
        return AnomalyResult(
            type="publisher_dominance",
            score=0.0,
            severity="ok",
            detail="top publisher count is zero",
        )

    ratio = top_count / total_titles

    if ratio >= PUBLISHER_DOMINANCE_THRESHOLD_HIGH:
        severity: Severity = "high"
    elif ratio >= PUBLISHER_DOMINANCE_THRESHOLD_MEDIUM:
        severity = "medium"
    else:
        severity = "ok"

    return AnomalyResult(
        type="publisher_dominance",
        score=round(ratio, 3),
        severity=severity,
        detail=(
            f"top publisher '{top_name}' contributes {top_count}/{total_titles} "
            f"titles ({ratio:.0%})"
        ),
    )


def detect_volume_spike(
    current_volume: int,
    baseline: list[int],
) -> AnomalyResult:
    """Détecte un pic de volume vs baseline N derniers cycles.

    Args:
        current_volume: nombre de titres collectés sur le cycle actuel.
        baseline: liste des volumes des cycles précédents (ordre indifférent
            puisqu'on ne fait que la moyenne). Doit contenir au moins
            `VOLUME_SPIKE_MIN_BASELINE_POINTS` éléments pour activer la
            détection — sinon severity=ok.

    Returns:
        AnomalyResult.
    """
    if len(baseline) < VOLUME_SPIKE_MIN_BASELINE_POINTS:
        return AnomalyResult(
            type="volume_spike",
            score=0.0,
            severity="ok",
            detail=(
                f"baseline insufficient ({len(baseline)} < "
                f"{VOLUME_SPIKE_MIN_BASELINE_POINTS} points)"
            ),
        )

    valid_baseline = [int(v) for v in baseline if isinstance(v, (int, float)) and v > 0]
    if not valid_baseline:
        return AnomalyResult(
            type="volume_spike",
            score=0.0,
            severity="ok",
            detail="baseline contains no valid (positive) values",
        )

    mean_baseline = sum(valid_baseline) / len(valid_baseline)
    if mean_baseline <= 0:
        return AnomalyResult(
            type="volume_spike",
            score=0.0,
            severity="ok",
            detail="baseline mean is zero",
        )

    if current_volume <= 0:
        return AnomalyResult(
            type="volume_spike",
            score=0.0,
            severity="ok",
            detail="current volume is zero",
        )

    ratio = current_volume / mean_baseline

    if ratio >= VOLUME_SPIKE_THRESHOLD_HIGH:
        severity: Severity = "high"
    elif ratio >= VOLUME_SPIKE_THRESHOLD_MEDIUM:
        severity = "medium"
    else:
        severity = "ok"

    return AnomalyResult(
        type="volume_spike",
        score=round(ratio, 2),
        severity=severity,
        detail=(
            f"current volume {current_volume} vs baseline mean {mean_baseline:.1f} (×{ratio:.2f})"
        ),
    )


def detect_publisher_diversity_spike(
    current_distinct_publishers: int,
    baseline: list[int],
    *,
    observation_mode: bool = PUBLISHER_DIVERSITY_OBSERVATION_MODE,
) -> AnomalyResult:
    """Détecte un pic de diversité d'éditeurs vs baseline N derniers cycles.

    Remplace `detect_volume_spike` pour CryptoCompare (backlog #8, Option B).
    L'API CryptoCompare renvoie ~50 articles par défaut → le volume brut est
    quasi constant (baseline `[50, 50, ...]`) → détection volume dormante. Le
    nombre d'éditeurs DISTINCTS couvrant l'actif sur un cycle est en revanche
    variable : un pic (beaucoup d'outlets sur la même story) signale un
    événement majeur (approbation ETF, hack, décision réglementaire).

    Mode observation (`observation_mode=True`, défaut) : le ratio est calculé
    et exposé dans `detail`, mais severity est forcée à "ok" — aucune
    pondération du bias en aval. Permet de mesurer empiriquement la corrélation
    pic ↔ événement sur plusieurs semaines AVANT d'activer le flag (cf. backlog
    #8 « valider empiriquement avant de coder dur » + garde-fou trading manuel
    actif). Passer `observation_mode=False` après calibration pour activer la
    sévérité.

    Args:
        current_distinct_publishers: nombre d'éditeurs distincts du cycle actuel
            (les "unknown" doivent être exclus en amont par le caller).
        baseline: comptes d'éditeurs distincts des cycles précédents (ordre
            indifférent, on ne fait que la moyenne). Doit contenir au moins
            `PUBLISHER_DIVERSITY_MIN_BASELINE_POINTS` éléments — sinon ok.
        observation_mode: si True, severity toujours "ok" (mesure sans agir).

    Returns:
        AnomalyResult (type="publisher_diversity_spike").
    """
    obs_suffix = " [observation]" if observation_mode else ""

    if len(baseline) < PUBLISHER_DIVERSITY_MIN_BASELINE_POINTS:
        return AnomalyResult(
            type="publisher_diversity_spike",
            score=0.0,
            severity="ok",
            detail=(
                f"baseline insufficient ({len(baseline)} < "
                f"{PUBLISHER_DIVERSITY_MIN_BASELINE_POINTS} points){obs_suffix}"
            ),
        )

    valid_baseline = [int(v) for v in baseline if isinstance(v, (int, float)) and v > 0]
    if not valid_baseline:
        return AnomalyResult(
            type="publisher_diversity_spike",
            score=0.0,
            severity="ok",
            detail=f"baseline contains no valid (positive) values{obs_suffix}",
        )

    mean_baseline = sum(valid_baseline) / len(valid_baseline)
    if mean_baseline <= 0:
        return AnomalyResult(
            type="publisher_diversity_spike",
            score=0.0,
            severity="ok",
            detail=f"baseline mean is zero{obs_suffix}",
        )

    if current_distinct_publishers <= 0:
        return AnomalyResult(
            type="publisher_diversity_spike",
            score=0.0,
            severity="ok",
            detail=f"current distinct publishers is zero{obs_suffix}",
        )

    ratio = current_distinct_publishers / mean_baseline

    if ratio >= PUBLISHER_DIVERSITY_SPIKE_THRESHOLD_HIGH:
        severity: Severity = "high"
    elif ratio >= PUBLISHER_DIVERSITY_SPIKE_THRESHOLD_MEDIUM:
        severity = "medium"
    else:
        severity = "ok"

    # Mode observation : on garde la métrique mais on n'agit pas (severity=ok).
    if observation_mode:
        severity = "ok"

    return AnomalyResult(
        type="publisher_diversity_spike",
        score=round(ratio, 2),
        severity=severity,
        detail=(
            f"{current_distinct_publishers} distinct publishers vs baseline mean "
            f"{mean_baseline:.1f} (×{ratio:.2f}){obs_suffix}"
        ),
    )
