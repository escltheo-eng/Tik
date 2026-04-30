"""Classifieurs de sentiment pour les titres de news financières.

Deux implémentations interchangeables :

- KeywordClassifier : analyse par listes de mots-clés (rapide, simple,
  limites documentées : ne gère pas négation/contexte/sarcasme).
- OllamaClassifier : appelle un LLM local via Ollama HTTP API
  (par défaut llama3.2:3b). Fallback automatique sur KeywordClassifier
  en cas d'erreur, avec circuit breaker batch-level (3 erreurs successives
  → bascule keywords pour le reste du batch, retry au cycle suivant).
  **Asset-aware** via le paramètre `asset_name` (défaut "Bitcoin") : le
  prompt précise au LLM pour quel asset on classifie le sentiment, ce qui
  permet d'instancier un classifier par couple (asset, ingester) avec
  des circuit breakers indépendants — voir ADR-008.

Sélection via la factory `build_news_classifier(...)`.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

import httpx
import structlog

log = structlog.get_logger()


# === Listes de mots-clés (déplacées de cryptocompare_ingester.py) ===
# Listes volontairement courtes mais distinctives (anglais uniquement, on
# filtre lang=EN sur l'API). Match par "le mot apparaît dans le titre".
# Enrichies 2026-04-29 après analyse de 20 titres réels qui montraient des
# faux négatifs (bottoming = bull contextuel, ease = bull) et faux positifs
# (lowers target = bear malgré "outperform" en suite).
BULLISH_KEYWORDS: set[str] = {
    # Direction haussière classique
    "surge", "surges", "soar", "soars", "rally", "rallies", "jump", "jumps",
    "gain", "gains", "rise", "rises", "rising", "rose", "climb", "climbs",
    "advance", "rebound", "rebounds", "recover", "recovers", "recovery",
    "skyrocket",
    # Marqueurs bull / accumulation
    "bull", "bullish", "moon", "pump", "breakthrough", "milestone", "record",
    "ath", "high", "uptrend", "bullrun",
    "accumulate", "accumulating", "accumulation",
    # Retournement / fin de baisse
    "bottom", "bottoming", "ease", "eases", "easing",
    "support", "supports", "supporting",
    # Régulation / institutionnels positifs
    "approval", "approve", "approved", "adopt", "adoption",
    "launch", "launches", "partnership", "upgrade", "upgrades",
    # Sentiment positif
    "boost", "boosts", "outperform", "optimistic", "optimism",
    "confidence", "win", "wins", "winning",
}

BEARISH_KEYWORDS: set[str] = {
    # Direction baissière classique
    "crash", "crashes", "plunge", "plunges", "dump", "dumps", "drop", "drops",
    "fall", "falls", "fell", "collapse", "collapses", "tumble", "tumbles",
    "slump", "slumps", "slip", "slips", "slide", "slides", "decline", "declines",
    # Marqueurs bear
    "bear", "bearish", "fear", "panic", "selloff", "sell-off",
    "loss", "losses", "downtrend", "pessimistic", "weak", "weakness",
    # Révisions à la baisse / downgrades
    "lowers", "lowered", "cuts", "downgrade", "downgrades",
    # Régulation / juridique négatifs
    "ban", "banned", "bans", "crackdown", "lawsuit", "sue", "sued", "sues",
    "prison", "arrest", "arrested", "shutdown",
    "delist", "delisted", "freeze", "freezes",
    # Crime / risque
    "hack", "hacked", "exploit", "scam", "fraud", "breach",
    "liquidation", "liquidate", "liquidated", "bankruptcy", "insolvency",
    # Sentiment négatif
    "warning", "concern", "concerns", "risk", "risks", "crisis",
}

# Tokeniseur simple : extrait les "mots" (lettres + apostrophes/tirets internes).
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


# === Interface commune ===


class NewsClassifier(ABC):
    """Interface : classifie un titre de news en (n_bullish, n_bearish)."""

    method_name: str = "base"

    @abstractmethod
    async def classify(self, title: str | None) -> tuple[int, int]:
        """Retourne (n_bull, n_bear) — chaque valeur est 0 ou 1 par titre."""
        ...

    def reset_batch(self) -> None:
        """Hook appelé en début de cycle. No-op par défaut, surchargé par
        OllamaClassifier pour réarmer son circuit breaker."""

    async def aclose(self) -> None:
        """Libère les ressources (clients HTTP, etc.). No-op par défaut."""


# === Implémentation 1 : keywords ===


class KeywordClassifier(NewsClassifier):
    """Classification par listes de mots-clés. Synchrone, rapide, limité."""

    method_name = "keywords"

    async def classify(self, title: str | None) -> tuple[int, int]:
        return self._classify_sync(title)

    @staticmethod
    def _classify_sync(title: str | None) -> tuple[int, int]:
        if not title:
            return 0, 0
        words = {w.lower() for w in WORD_RE.findall(title)}
        return len(words & BULLISH_KEYWORDS), len(words & BEARISH_KEYWORDS)


# === Implémentation 2 : Ollama (LLM local) ===


class OllamaClassifier(NewsClassifier):
    """Classification via un LLM local Ollama. Fallback keywords sur erreur.

    Asset-aware : le prompt mentionne explicitement {asset_name} pour
    donner le contexte au LLM. Permet de classifier le sentiment news
    pour Bitcoin, Gold, Ethereum, ou tout autre asset, depuis un même
    backend Ollama, avec un circuit breaker dédié à chaque instance.
    """

    PROMPT_TEMPLATE = (
        "You are a financial sentiment classifier for news headlines. "
        "Classify the following headline by its likely impact on the {asset_name} price. "
        "Reply with EXACTLY one word: BULLISH, BEARISH, or NEUTRAL.\n\n"
        'Headline: "{title}"'
    )

    # Au-delà de N erreurs successives dans le même batch, on bascule sur
    # le fallback keywords pour les titres restants du batch. Le compteur
    # est remis à zéro à chaque cycle via reset_batch().
    FAILURE_THRESHOLD = 3

    def __init__(
        self,
        url: str,
        model: str,
        asset_name: str = "Bitcoin",
        fallback: NewsClassifier | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.asset_name = asset_name
        self.fallback = fallback or KeywordClassifier()
        self.timeout_s = timeout_s
        self._consecutive_failures = 0
        self._batch_circuit_open = False
        self._client: httpx.AsyncClient | None = None

    @property
    def method_name(self) -> str:  # type: ignore[override]
        return f"ollama:{self.model}"

    def reset_batch(self) -> None:
        self._consecutive_failures = 0
        self._batch_circuit_open = False

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def classify(self, title: str | None) -> tuple[int, int]:
        if not title:
            return 0, 0
        if self._batch_circuit_open:
            return await self.fallback.classify(title)

        try:
            verdict = await self._call_ollama(title)
        except Exception as exc:  # noqa: BLE001
            self._consecutive_failures += 1
            log.warning(
                "news_classifier.ollama_error",
                error=str(exc),
                asset=self.asset_name,
                consecutive_failures=self._consecutive_failures,
            )
            if self._consecutive_failures >= self.FAILURE_THRESHOLD:
                self._batch_circuit_open = True
                log.warning(
                    "news_classifier.ollama_circuit_open_for_batch",
                    asset=self.asset_name,
                    threshold=self.FAILURE_THRESHOLD,
                )
            return await self.fallback.classify(title)

        self._consecutive_failures = 0
        return self._verdict_to_counts(verdict, title)

    async def _call_ollama(self, title: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            asset_name=self.asset_name,
            title=title.replace('"', "'"),
        )
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
        r = await self._client.post(
            f"{self.url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 10},
            },
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("response") or "").strip()

    @staticmethod
    def _verdict_to_counts(verdict: str, title: str) -> tuple[int, int]:
        """Parse tolérant : on cherche le 1er mot-clé connu dans la réponse."""
        upper = verdict.upper()
        positions: dict[str, int] = {}
        for label in ("BULLISH", "BEARISH", "NEUTRAL"):
            idx = upper.find(label)
            if idx >= 0:
                positions[label] = idx
        if not positions:
            log.warning(
                "news_classifier.ollama_unparsable_response",
                response=verdict[:80],
                title=title[:80],
            )
            return 0, 0
        first_label = min(positions.items(), key=lambda kv: kv[1])[0]
        if first_label == "BULLISH":
            return 1, 0
        if first_label == "BEARISH":
            return 0, 1
        return 0, 0  # NEUTRAL


# === Factory ===


async def build_news_classifier(
    classifier_type: str,
    ollama_url: str,
    ollama_model: str,
    asset_name: str = "Bitcoin",
) -> NewsClassifier:
    """Sélectionne le classifier selon la config et vérifie la santé d'Ollama
    si demandé. En cas d'indisponibilité d'Ollama, fallback sur keywords.

    `asset_name` est passé au constructeur de `OllamaClassifier` pour que
    le prompt au LLM précise pour quel asset on classifie le sentiment.
    Pour le `KeywordClassifier` (analyse par mots-clés agnostique), le
    paramètre est loggué mais n'a pas d'effet sur la classification.
    """
    if classifier_type == "keywords":
        log.info("news_classifier.using_keywords", asset=asset_name)
        return KeywordClassifier()

    # classifier_type == "ollama" (défaut)
    if await _ollama_alive(ollama_url, ollama_model):
        log.info(
            "news_classifier.ollama_ready",
            url=ollama_url,
            model=ollama_model,
            asset=asset_name,
        )
        return OllamaClassifier(
            url=ollama_url,
            model=ollama_model,
            asset_name=asset_name,
        )

    log.warning(
        "news_classifier.ollama_unavailable_fallback_keywords",
        url=ollama_url,
        model=ollama_model,
        asset=asset_name,
    )
    return KeywordClassifier()


async def _ollama_alive(url: str, model: str) -> bool:
    """Ping Ollama et vérifie que le modèle demandé est disponible."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{url.rstrip('/')}/api/tags")
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("news_classifier.ollama_ping_failed", error=str(exc))
        return False
    available = {m.get("name", "") for m in data.get("models", [])}
    if model not in available:
        log.warning(
            "news_classifier.ollama_model_missing",
            requested=model,
            available=sorted(available),
        )
        return False
    return True
