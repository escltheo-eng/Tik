"""Génération contextuelle de l'hypothèse d'un signal Tik.

Pattern Strategy identique à `news_classifier.py` (cf. ADR-006) :

- TemplateHypothesisGenerator : f-string déterministe (fallback historique).
- OllamaHypothesisGenerator   : appelle un LLM local via Ollama HTTP API
  pour synthétiser evidence + triggers + counter_scenarios + statut anti
  fake-news en un texte structuré ~150 mots EN. Fallback automatique sur
  TemplateHypothesisGenerator en cas d'erreur, avec circuit breaker
  batch-level (3 erreurs successives → bascule template pour le reste du
  batch, retry au cycle suivant).

L'objet `decision` est duck-typé pour éviter un import circulaire des
dataclasses SwingDecision/FlashDecision. Les attributs attendus :
entity_id, direction, confidence, veracity, evidence, triggers,
counter_scenarios, circuit_breaker_status, advisory (dict).

Voir ADR-012 — LLM hypothesis generator.
"""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx
import structlog

log = structlog.get_logger()


# === Render template (utilisé en fallback ET en mode disabled) ===


def render_template_hypothesis(decision: Any, horizon: str) -> str:
    """Hypothèse template historique (déterministe, ~12 mots).

    Identique au format des f-strings que portent aujourd'hui swing_engine
    et flash_engine — extrait ici pour pouvoir s'y rabattre en fallback
    sans dupliquer la logique.
    """
    horizon_label = horizon.capitalize()
    return (
        f"{horizon_label} {decision.direction} on {decision.entity_id} "
        f"based on technical/sentiment confluence "
        f"(confidence={decision.confidence:.2f}, "
        f"veracity={decision.veracity:.2f})"
    )


# === Interface commune ===


class HypothesisGenerator(ABC):
    """Interface : génère un texte d'hypothèse à partir d'une décision."""

    method_name: str = "base"

    @abstractmethod
    async def generate(self, decision: Any, horizon: str) -> str:
        """Retourne le texte d'hypothèse pour la decision donnée."""
        ...

    def reset_batch(self) -> None:
        """Hook appelé en début de cycle. No-op par défaut, surchargé par
        OllamaHypothesisGenerator pour réarmer son circuit breaker."""

    async def aclose(self) -> None:
        """Libère les ressources (clients HTTP, etc.). No-op par défaut."""


# === Implémentation 1 : template (fallback) ===


class TemplateHypothesisGenerator(HypothesisGenerator):
    """Génère l'hypothèse via le template f-string. Synchrone, déterministe."""

    method_name = "template"

    async def generate(self, decision: Any, horizon: str) -> str:
        return render_template_hypothesis(decision, horizon)


# === Implémentation 2 : Ollama (LLM local) ===


# Limites de validation post-génération
MIN_WORDS = 50
MAX_WORDS = 400
MARKDOWN_RE = re.compile(r"(\*\*|##|```|__)")

# Patterns d'hallucination de prix : le LLM 3B a tendance à inventer des
# niveaux du genre "$50,000" ou "$1,800 USD" qui ne sont jamais dans les
# inputs (Tik ne fournit pas le prix courant au prompt, uniquement RSI,
# EMA, MACD, scores). Si un de ces patterns matche le texte généré ET ne
# se retrouve pas verbatim dans les `fact`/`value` des inputs decision,
# c'est une hallucination → fallback template.
PRICE_PATTERNS = [
    re.compile(r"\$\s*\d[\d,.]*"),  # "$50,000", "$1.8k", "$78400"
    re.compile(
        r"\b\d[\d,.]*\s*(?:USD|EUR|dollars?|euros?)\b",
        re.IGNORECASE,
    ),  # "50000 USD", "1,800 dollars"
]


class OllamaHypothesisGenerator(HypothesisGenerator):
    """Génération via LLM local Ollama. Fallback template sur erreur.

    Le prompt est structuré en 6 sections fixes (verdict, technical,
    sentiment, anti fake-news, risk, watch) avec des contraintes strictes
    (pas d'invention de prix/sources, pas de markdown, longueur 120-180
    mots). Validation post-génération avant retour : si le texte ne
    respecte pas les contraintes minimales, fallback template.
    """

    PROMPT_TEMPLATE = (
        "You are a financial signals analyst. Generate a structured "
        "hypothesis text for the following Tik trading signal.\n\n"
        "INPUT DATA:\n"
        "- Asset: {entity_id}\n"
        "- Horizon: {horizon}\n"
        "- Direction: {direction}\n"
        "- Confidence: {confidence:.2f}\n"
        "- Veracity: {veracity:.2f}\n"
        "- Anti fake-news status: {cb_status}{outliers_str}\n\n"
        "Technical triggers:\n"
        "{triggers}\n\n"
        "Evidence sources:\n"
        "{evidence}\n\n"
        "Counter-scenarios:\n"
        "{counter_scenarios}\n\n"
        "OUTPUT FORMAT (6 sections, fixed order, ~150 words total):\n"
        "1. Verdict and quality (1 sentence): direction + asset + "
        "confidence + veracity, qualify the concordance.\n"
        "2. Technical reading (1-2 sentences): which indicators converge, "
        "quote ONLY values present in 'Technical triggers' or 'Evidence "
        "sources' above (RSI value, EMA values, MACD value).\n"
        "3. Sentiment cross-validation (2-3 sentences): name each "
        "non-technical source with its bias and a short descriptor.\n"
        "4. Anti fake-news status (1 sentence): repeat the status value "
        "given in the input (ok / degraded / tripped). If outliers are "
        "listed, name them. Otherwise say 'no source flagged'. Do NOT "
        "contradict the input status.\n"
        "5. Main risk (1-2 sentences): pick the counter-scenario with "
        "the HIGHEST probability listed above, name it explicitly, "
        "quote its probability, restate its mitigation.\n"
        "6. Watch (1 sentence): describe what indicator threshold or "
        "counter-scenario condition would invalidate the thesis. Quote "
        "ONLY indicator values present in the input (e.g., 'RSI breaking "
        "above 75', 'EMA9/EMA21 crossover reversal', 'macro_shock counter"
        "-scenario activation'). Do NOT invent specific price levels.\n\n"
        "STRICT CONSTRAINTS — VIOLATIONS WILL TRIGGER FALLBACK:\n"
        "- Use ONLY the data provided above. Every number, source name, "
        "counter-scenario name MUST come from the input.\n"
        "- Do NOT cite price levels in dollars/euros (e.g. '$50,000', "
        "'$1,800'). Prices are NOT in the input data.\n"
        "- Do NOT contradict the input. If sentiment score is negative, "
        "do NOT call it bullish. If status is 'ok', do NOT say sources "
        "are flagged.\n"
        "- Do NOT invent ETF flows, news headlines, FOMC dates, "
        "geopolitical events, or any external context not in the input.\n"
        "- Output ONLY the hypothesis text in the 6-section structure.\n"
        "- No preamble, no closing remark, no markdown formatting "
        "(no **, ##, ```, __).\n"
        "- 120-180 words total. English only.\n\n"
        "HYPOTHESIS:\n"
    )

    # Au-delà de N erreurs successives dans le même batch, on bascule sur
    # le fallback template pour les decisions restantes du batch. Le
    # compteur est remis à zéro à chaque cycle via reset_batch().
    FAILURE_THRESHOLD = 3

    def __init__(
        self,
        url: str,
        model: str,
        fallback: HypothesisGenerator | None = None,
        timeout_s: float = 50.0,
        num_predict: int = 350,
        lock: asyncio.Lock | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.fallback = fallback or TemplateHypothesisGenerator()
        self.timeout_s = timeout_s
        self.num_predict = num_predict
        # Lock optionnel partagé entre instances pour sérialiser les
        # appels HTTP Ollama. Indispensable côté scheduler où 3 jobs
        # (swing BTC + swing GOLD + flash BTC) peuvent tomber sur le
        # même tick (xx:00, xx:30) et saturer Ollama même avec
        # OLLAMA_NUM_PARALLEL=2 → 1 timeout assuré sur le 3e job. Un
        # Lock partagé dans le scheduler force la sérialisation
        # coût-side Tik. Cumulé : 13s × 3 = 40s, sous l'interval
        # min 5 min flash. Pas de Lock dans les tests/CI ou en mode
        # standalone : appels parallèles libres.
        self._lock = lock
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

    async def generate(self, decision: Any, horizon: str) -> str:
        if self._batch_circuit_open:
            return await self.fallback.generate(decision, horizon)

        try:
            if self._lock is not None:
                # Sérialise l'appel HTTP Ollama (mais PAS la
                # validation/sanitize qui sont purement Python et
                # rapides). Côté scheduler, ça empêche 3 jobs
                # concurrents de saturer Ollama.
                async with self._lock:
                    raw = await self._call_ollama(decision, horizon)
            else:
                raw = await self._call_ollama(decision, horizon)
        except Exception as exc:  # noqa: BLE001
            self._consecutive_failures += 1
            # str(exc) est souvent vide pour httpx.ReadTimeout / asyncio
            # CancelledError — utiliser le repr() pour avoir au moins le
            # type d'exception, indispensable pour diagnostiquer en prod
            # (concurrence Ollama, network reset, modèle déchargé, etc.)
            log.warning(
                "hypothesis_generator.ollama_error",
                error_type=type(exc).__name__,
                error_repr=repr(exc)[:200],
                entity_id=decision.entity_id,
                horizon=horizon,
                consecutive_failures=self._consecutive_failures,
            )
            if self._consecutive_failures >= self.FAILURE_THRESHOLD:
                self._batch_circuit_open = True
                log.warning(
                    "hypothesis_generator.ollama_circuit_open_for_batch",
                    threshold=self.FAILURE_THRESHOLD,
                )
            return await self.fallback.generate(decision, horizon)

        cleaned = self._sanitize_output(raw)
        if not self._is_valid_output(cleaned, decision):
            log.warning(
                "hypothesis_generator.ollama_invalid_output",
                entity_id=decision.entity_id,
                horizon=horizon,
                length_chars=len(raw),
                preview=raw[:120],
            )
            # Sortie LLM invalide : pas un échec réseau, on ne touche pas
            # au compteur du circuit breaker — c'est juste un loupé
            # ponctuel du modèle. Fallback template sur cette decision.
            return await self.fallback.generate(decision, horizon)

        invented = self._find_invented_prices(cleaned, decision)
        if invented:
            log.warning(
                "hypothesis_generator.ollama_invented_price",
                entity_id=decision.entity_id,
                horizon=horizon,
                invented=invented[:5],
                preview=cleaned[:200],
            )
            return await self.fallback.generate(decision, horizon)

        self._consecutive_failures = 0
        return cleaned

    async def _call_ollama(self, decision: Any, horizon: str) -> str:
        prompt = self.PROMPT_TEMPLATE.format(
            entity_id=decision.entity_id,
            horizon=horizon,
            direction=decision.direction,
            confidence=decision.confidence,
            veracity=decision.veracity,
            cb_status=getattr(decision, "circuit_breaker_status", "ok"),
            outliers_str=self._format_outliers(decision),
            triggers=self._format_triggers(decision.triggers),
            evidence=self._format_evidence(decision.evidence),
            counter_scenarios=self._format_counter_scenarios(
                decision.counter_scenarios
            ),
        )
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
        r = await self._client.post(
            f"{self.url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_predict": self.num_predict,
                },
            },
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("response") or "").strip()

    @staticmethod
    def _format_triggers(triggers: list[dict]) -> str:
        if not triggers:
            return "  (none)"
        lines = []
        for t in triggers:
            t_type = t.get("type", "?")
            t_value = t.get("value", "?")
            t_weight = t.get("weight", 0.0)
            lines.append(f"- {t_type} (weight {t_weight:.2f}): {t_value}")
        return "\n".join(lines)

    @staticmethod
    def _format_evidence(evidence: list[dict]) -> str:
        if not evidence:
            return "  (none)"
        lines = []
        for e in evidence:
            src = e.get("source", "?")
            score = e.get("score", 0.0)
            fact = e.get("fact", "?")
            outlier = " [OUTLIER]" if e.get("is_outlier") else ""
            lines.append(f"- {src} (credibility {score:.2f}){outlier}: {fact}")
        return "\n".join(lines)

    @staticmethod
    def _format_counter_scenarios(scenarios: list[dict]) -> str:
        if not scenarios:
            return "  (none)"
        lines = []
        for cs in scenarios:
            name = cs.get("name", "?")
            prob = cs.get("probability", 0.0)
            mitigation = cs.get("mitigation", "?")
            lines.append(
                f"- {name} (probability {prob:.2f}): {mitigation}"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_outliers(decision: Any) -> str:
        outliers = [
            e.get("source", "?")
            for e in decision.evidence
            if e.get("is_outlier")
        ]
        if not outliers:
            return ""
        return f" (outliers detected: {', '.join(outliers)})"

    @staticmethod
    def _sanitize_output(raw: str) -> str:
        """Supprime markdown éventuel, normalise les whitespaces."""
        text = MARKDOWN_RE.sub("", raw).strip()
        # Compact les triple newlines à double, mais préserve les retours
        # de section. Évite les blank lines abusives.
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    @staticmethod
    def _is_valid_output(text: str, decision: Any) -> bool:
        """Validation post-génération (longueur + mots-clés obligatoires).

        Garde-fou contre hallucinations grossières et timeout silencieux.
        Si invalide → fallback template.
        """
        n_words = len(text.split())
        if n_words < MIN_WORDS or n_words > MAX_WORDS:
            return False
        upper = text.upper()
        if decision.direction.upper() not in upper:
            return False
        if decision.entity_id.upper() not in upper:
            return False
        return True

    @staticmethod
    def _find_invented_prices(text: str, decision: Any) -> list[str]:
        """Détecte les patterns prix ($XXX,XXX, NNNN USD) dans la sortie
        qui ne se retrouvent PAS verbatim dans les inputs decision.

        Tik ne fournit jamais le prix courant en $ au LLM (uniquement
        RSI, EMA, MACD, scores de sentiment). Si le LLM cite un prix
        en $, il l'a inventé. Retourne la liste des matchs problématiques
        (vide = OK) — limitée à 5 entrées pour ne pas spam les logs.
        """
        allowed_text = " ".join(
            [str(e.get("fact", "")) for e in decision.evidence]
            + [str(t.get("value", "")) for t in decision.triggers]
        )
        invented: list[str] = []
        for pattern in PRICE_PATTERNS:
            for match in pattern.finditer(text):
                matched = match.group(0).strip()
                if matched not in allowed_text:
                    invented.append(matched)
                    if len(invented) >= 5:
                        return invented
        return invented


# === Helper d'application pour les engines ===


async def apply_llm_hypothesis(
    decision: Any,
    horizon: str,
    generator: HypothesisGenerator | None,
    mode: str,
    timeout_s: float = 60.0,
) -> None:
    """Applique le generator à la decision en place selon le mode.

    Modes :
    - "disabled" : no-op, decision.hypothesis garde le template
    - "shadow"   : génère le LLM, stocke dans decision.advisory
                   ["llm_hypothesis_candidate"], decision.hypothesis
                   garde le template — validation passive
    - "active"   : génère le LLM, remplace decision.hypothesis ;
                   decision.advisory["template_hypothesis"] conserve
                   l'ancienne pour audit

    Le timeout `timeout_s` enveloppe l'appel `generator.generate()` —
    fixé à 60s par défaut, légèrement supérieur au timeout HTTP interne
    du generator (50s) pour laisser une marge sans déclencher deux
    erreurs en cascade. Calibré sur la latence mesurée de llama3.2:3b
    sur Mac M1 (~13s/cycle pour ~250 mots) avec marge pour les
    prompts swing plus lourds (~30-40s observés en pic) et la
    sérialisation Lock côté scheduler (3 jobs séquentiels = 40s cumulé).
    Ne lève jamais : tout échec est loggué et la decision reste
    inchangée (= conserve son hypothèse template).
    """
    if generator is None or mode == "disabled":
        return

    try:
        llm_text = await asyncio.wait_for(
            generator.generate(decision, horizon),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        log.warning(
            "hypothesis_generator.timeout",
            entity_id=decision.entity_id,
            horizon=horizon,
            timeout_s=timeout_s,
        )
        return
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "hypothesis_generator.unexpected_error",
            entity_id=decision.entity_id,
            horizon=horizon,
            error=str(exc),
        )
        return

    # Détection de fallback : si le generator (Ollama) a fallback sur son
    # template interne (timeout, sortie invalide, prix inventé, circuit
    # breaker ouvert), le texte retourné est exactement le rendu template
    # — pas un vrai contenu LLM. On ne stocke alors RIEN dans
    # `advisory.llm_hypothesis_candidate` (mode shadow) ni rien à
    # remplacer (mode active) pour éviter d'afficher dans le dashboard
    # une carte "LLM · validation" qui ne contient pas de texte LLM.
    template_text = render_template_hypothesis(decision, horizon)
    is_fallback = (llm_text.strip() == template_text.strip())

    if mode == "shadow":
        if is_fallback:
            log.info(
                "hypothesis_generator.shadow.fallback",
                entity_id=decision.entity_id,
                horizon=horizon,
                reason="llm_returned_template_no_candidate_stored",
            )
            return
        if not isinstance(decision.advisory, dict):
            decision.advisory = {}
        decision.advisory["llm_hypothesis_candidate"] = llm_text
        log.info(
            "hypothesis_generator.shadow.candidate",
            entity_id=decision.entity_id,
            horizon=horizon,
            method=getattr(generator, "method_name", "unknown"),
            length_words=len(llm_text.split()),
        )
        return

    if mode == "active":
        if is_fallback:
            log.info(
                "hypothesis_generator.active.fallback",
                entity_id=decision.entity_id,
                horizon=horizon,
                reason="llm_returned_template_kept_as_is",
            )
            return
        if not isinstance(decision.advisory, dict):
            decision.advisory = {}
        decision.advisory["template_hypothesis"] = decision.hypothesis
        decision.hypothesis = llm_text
        log.info(
            "hypothesis_generator.active.applied",
            entity_id=decision.entity_id,
            horizon=horizon,
            method=getattr(generator, "method_name", "unknown"),
            length_words=len(llm_text.split()),
        )
        return

    log.warning(
        "hypothesis_generator.unknown_mode",
        mode=mode,
        entity_id=decision.entity_id,
    )


# === Factory ===


async def build_hypothesis_generator(
    generator_type: str,
    ollama_url: str,
    ollama_model: str,
    lock: asyncio.Lock | None = None,
) -> HypothesisGenerator:
    """Sélectionne le generator selon la config et vérifie la santé Ollama.

    En cas d'indisponibilité Ollama, fallback sur TemplateHypothesisGenerator.
    Retour direct pour `generator_type == "template"` (skip ping).

    Le `lock` optionnel est passé à `OllamaHypothesisGenerator` pour
    sérialiser les appels HTTP Ollama. Utilisé côté scheduler pour
    éviter la concurrence interne entre les 3 jobs (swing BTC + GOLD
    + flash BTC) qui peuvent saturer Ollama même avec NUM_PARALLEL=2.
    """
    if generator_type == "template":
        log.info("hypothesis_generator.using_template")
        return TemplateHypothesisGenerator()

    # generator_type == "ollama"
    if await _ollama_alive(ollama_url, ollama_model):
        log.info(
            "hypothesis_generator.ollama_ready",
            url=ollama_url,
            model=ollama_model,
            lock_enabled=lock is not None,
        )
        return OllamaHypothesisGenerator(
            url=ollama_url,
            model=ollama_model,
            lock=lock,
        )

    log.warning(
        "hypothesis_generator.ollama_unavailable_fallback_template",
        url=ollama_url,
        model=ollama_model,
    )
    return TemplateHypothesisGenerator()


async def _ollama_alive(url: str, model: str) -> bool:
    """Ping Ollama et vérifie que le modèle demandé est disponible."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{url.rstrip('/')}/api/tags")
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("hypothesis_generator.ollama_ping_failed", error=str(exc))
        return False
    available = {m.get("name", "") for m in data.get("models", [])}
    if model not in available:
        log.warning(
            "hypothesis_generator.ollama_model_missing",
            requested=model,
            available=sorted(available),
        )
        return False
    return True
