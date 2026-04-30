"""Exemple 3 — Pseudo-overlay sur turbo_v2.py de Zeta.

⚠️  CET EXEMPLE N'EST PAS RUNNABLE. C'est du pseudo-code annoté qui
montre comment câbler le SDK Tik dans `cranial_bot/turbo_v2.py` de Zeta
SANS bypass du guard V01-V15 (ADR-003). Les classes `InternalSignal`,
`MicroLiveGuard`, `RiskEngine` sont des stubs pour la lisibilité.

Pour une version exhaustive avec tous les patterns (overlay confidence,
hook crash, V16, telemetry feedback) : voir `docs/integration_zeta.md`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from tik_sdk import (
    ApiKeyAuth,
    CircuitBreaker,
    InMemoryCache,
    TikClient,
    TikError,
)


# ============================================================================
# Stubs — Zeta-side, pour la démo
# ============================================================================


@dataclass
class InternalSignal:
    """Signal Zeta interne (sortie de l'analyse technique propre à Zeta)."""

    symbol: str          # "BTC" ou "GOLD"
    direction: str       # "long" | "short" | "neutral"
    confidence: float    # ∈ [0, 1]
    tik_signal_id: str | None = None  # rempli par l'overlay si Tik a contribué


class MicroLiveGuard:
    """Stub — en réalité c'est le pipeline V01-V15 de Zeta."""

    async def evaluate(self, signal: InternalSignal) -> tuple[bool, str]:
        # 15 checks bloquants en vrai (spread, marge, kill switch, etc.)
        return (True, "all_checks_passed")


class RiskEngine:
    """Stub — en réalité c'est le service qui dimensionne et envoie l'ordre MT5."""

    async def size_and_send(self, signal: InternalSignal) -> None:
        print(
            f"[RISK_ENGINE] {signal.direction.upper()} {signal.symbol} "
            f"avec confidence finale {signal.confidence:.3f}"
        )


# ============================================================================
# Le vrai sujet — l'overlay Tik
# ============================================================================


class TikOverlay:
    """Encapsule le client Tik et la logique d'overlay confidence.

    Conforme ADR-003 :
    - Aucun appel `place_order` (le SDK n'en a pas, vérifié par test).
    - Le guard V01-V15 reste appelé sans modification après l'overlay.
    - Si Tik est down → overlay no-op, Zeta continue normalement.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._client: TikClient | None = None

    async def __aenter__(self) -> TikOverlay:
        self._client = TikClient(
            self._base_url,
            ApiKeyAuth(self._api_key),
            cache=InMemoryCache(maxsize=500),
            circuit_breaker=CircuitBreaker(failure_threshold=5, reset_timeout_s=30),
        )
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client:
            await self._client.__aexit__(None, None, None)

    async def apply(self, signal: InternalSignal) -> InternalSignal:
        """Module la confidence de `signal` selon le dernier signal Tik."""
        assert self._client is not None

        try:
            tik_signals = await self._client.get_latest_signals(
                entity=signal.symbol,
                horizon="swing",
                limit=1,
            )
        except TikError:
            # Tik down → on continue sans overlay (ADR-003)
            return signal

        if not tik_signals:
            return signal

        tik = tik_signals[0]

        # Garde-fous : signal expiré ou circuit breaker côté core
        if tik.expiry and tik.expiry < datetime.utcnow():
            return signal
        if tik.circuit_breaker_status != "ok":
            return signal

        factor = tik.confidence * tik.veracity

        if tik.direction == signal.direction:
            # Concordance Tik ↔ Zeta : on boost la confidence
            boost = factor * 0.20  # max +20%
            signal.confidence = min(1.0, signal.confidence + boost)
        elif tik.direction != "neutral":
            # Divergence : on baisse la confidence
            penalty = factor * 0.15  # max -15%
            signal.confidence = max(0.0, signal.confidence - penalty)
        # else: tik.direction == "neutral" → pas de modulation

        signal.tik_signal_id = tik.id
        return signal


# ============================================================================
# Boucle de décision — comment ça s'intègre
# ============================================================================


async def turbo_v2_evaluate_one_tick(
    market_data: dict,
    overlay: TikOverlay,
    guard: MicroLiveGuard,
    risk: RiskEngine,
) -> None:
    """Une itération de la boucle de décision Zeta avec overlay Tik."""

    # 1. Analyse technique propre à Zeta (stub)
    internal = InternalSignal(
        symbol=market_data["symbol"],
        direction="long",
        confidence=0.65,
    )

    # 2. Overlay Tik — UNE LIGNE — avant le guard
    internal = await overlay.apply(internal)

    # 3. Guard V01-V15 INCHANGÉ — Tik ne le contourne JAMAIS
    allowed, reason = await guard.evaluate(internal)
    if not allowed:
        print(f"[GUARD] blocked: {reason}")
        return

    # 4. Risk engine INCHANGÉ — Tik ne dimensionne JAMAIS
    await risk.size_and_send(internal)


# ============================================================================
# Démonstration
# ============================================================================


async def main() -> None:
    import os

    api_key = os.environ.get("TIK_API_KEY")
    base_url = os.environ.get("TIK_BASE_URL", "http://localhost:8200")
    if not api_key:
        raise SystemExit("TIK_API_KEY env var is required for the demo")

    guard = MicroLiveGuard()
    risk = RiskEngine()

    async with TikOverlay(base_url, api_key) as overlay:
        # Simule 2 ticks de marché
        await turbo_v2_evaluate_one_tick({"symbol": "BTC"}, overlay, guard, risk)
        await turbo_v2_evaluate_one_tick({"symbol": "GOLD"}, overlay, guard, risk)


if __name__ == "__main__":
    asyncio.run(main())
