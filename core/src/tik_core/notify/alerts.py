"""Alertes Telegram entre les briefings — best-effort, déterministe.

Deux déclencheurs (zéro prédiction, cohérent NO-GO — c'est de la DÉTECTION et
de la mise en contexte, pas un signal directionnel) :

1. **Choc de prix BTC** : mouvement ≥ seuil sur une fenêtre courte (la « chute
   libre »). Les titres récents sont attachés pour le « pourquoi ».
2. **Événement macro HIGH imminent** : pré-alerte ≤ N min avant (NFP, CPI,
   FOMC, BCE…), pour la discipline ±4h.

Anti-spam (Redis) :
- Choc : on stocke une **ancre** {price, ts} ; on ne ré-alerte qu'après un
  nouveau mouvement ≥ seuil depuis l'ancre, OU après un délai de garde (cooldown).
- Macro : un **set** d'events déjà alertés → 1 alerte par event.

Best-effort : aucune exception ne remonte ; on n'écrit l'ancre / le set QUE si
l'envoi Telegram a réussi (un échec transitoire est ainsi retenté au cycle suivant).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tik_core.config import Settings, get_settings
from tik_core.notify.briefing import (
    _fetch_headlines_and_climate,
    _sentiment_emoji,
    technical_read,
)
from tik_core.notify.telegram import escape_html, send_message
from tik_core.scripts.backtest import fetch_btc_history, find_closest_price
from tik_core.storage.macro_events_repo import fetch_upcoming
from tik_core.storage.models import MacroEvent
from tik_core.utils.time import now_utc_naive

log = structlog.get_logger()

# --- Paramètres (pifomètre raisonné, à calibrer post-usage) ---
PRICE_SHOCK_PCT = 3.0  # |mouvement| ≥ 3 % …
PRICE_SHOCK_WINDOW_H = 6  # … sur 6 h glissantes
PRICE_SHOCK_COOLDOWN_S = 4 * 3600  # délai de garde entre 2 alertes de choc
MACRO_LEAD_MIN = 60  # pré-alerte si event HIGH dans ≤ 60 min
N_ALERT_HEADLINES = 2

ANCHOR_KEY = "tik.alert.price.btc"  # {"price": float, "ts": int(sec)}
ANCHOR_TTL_S = 24 * 3600
MACRO_SENT_KEY = "tik.alert.macro.sent"  # set d'event keys déjà alertés
MACRO_SENT_TTL_S = 3 * 24 * 3600

# Bascule du régime de risque (ADR-035, VIX/crédit) — CONTEXTE, pas prédiction.
MACRO_REGIME_KEY = "tik.macro.regime"
RISK_STATE_KEY = "tik.alert.risk_state.last"  # dernier risk_state alerté/vu
RISK_STATE_TTL_S = 30 * 24 * 3600
KNOWN_RISK_STATES = frozenset({"risk_on", "neutral", "risk_off"})


# ---------------- helpers purs (testables) ----------------


def price_move_over_window(
    history: list[tuple[int, float]], window_h: int
) -> tuple[float | None, float | None]:
    """Retourne (prix actuel, variation % sur `window_h`). Pur.

    (None, None) si historique trop court ; (prix, None) si le point d'il y a
    `window_h` heures est introuvable dans la marge.
    """
    if len(history) < 2:
        return None, None
    last_ts, now_price = history[-1]
    target = datetime.fromtimestamp((last_ts - window_h * 3600 * 1000) / 1000, tz=UTC)
    p0 = find_closest_price(history, target, max_diff_ms=2 * 3600 * 1000)
    if not p0:
        return now_price, None
    return now_price, (now_price / p0 - 1) * 100


def should_alert_shock(
    move_pct: float | None,
    now_price: float | None,
    now_ts: int,
    anchor: dict | None,
    *,
    threshold: float = PRICE_SHOCK_PCT,
    cooldown_s: int = PRICE_SHOCK_COOLDOWN_S,
) -> tuple[bool, dict | None]:
    """Décide d'alerter un choc + renvoie la nouvelle ancre. Pur.

    Alerte si |move_pct| ≥ threshold ET (pas d'ancre OU prix a bougé d'un
    nouveau ≥ threshold depuis l'ancre OU délai de garde dépassé). Sinon non.
    """
    if move_pct is None or now_price is None or abs(move_pct) < threshold:
        return False, anchor
    if not anchor or not anchor.get("price"):
        return True, {"price": now_price, "ts": now_ts}
    moved_since = abs(now_price / anchor["price"] - 1) * 100
    elapsed = now_ts - int(anchor.get("ts", 0))
    if moved_since >= threshold or elapsed >= cooldown_s:
        return True, {"price": now_price, "ts": now_ts}
    return False, anchor


def imminent_macro(
    events: list[MacroEvent], now_naive: datetime, lead_min: int = MACRO_LEAD_MIN
) -> list[MacroEvent]:
    """Filtre les events dont l'échéance est dans [now, now + lead_min]. Pur."""
    out: list[MacroEvent] = []
    for e in events:
        delta_min = (e.scheduled_for - now_naive).total_seconds() / 60
        if 0 <= delta_min <= lead_min:
            out.append(e)
    return out


def macro_event_key(e: MacroEvent) -> str:
    return f"{e.event_code}|{e.scheduled_for.isoformat()}"


def format_shock_alert(
    *,
    p0: float | None,
    now_price: float,
    move_pct: float,
    window_h: int,
    tech: dict | None,
    headlines: list[dict],
) -> str:
    arrow = "🔻" if move_pct < 0 else "🔺"
    lines = [f"{arrow} <b>Alerte BTC — choc de prix</b>"]
    if p0:
        lines.append(f"<b>{move_pct:+.1f}%</b> en {window_h}h : {p0:,.0f}$ → {now_price:,.0f}$")
    else:
        lines.append(f"<b>{move_pct:+.1f}%</b> en {window_h}h → {now_price:,.0f}$")
    if tech:
        lines.append(f"🧭 {tech['trend']} · {tech['rsi_label']}")
    if headlines:
        lines.append("")
        lines.append("📰 <b>Contexte</b>")
        for h in headlines[:N_ALERT_HEADLINES]:
            emo = _sentiment_emoji(h.get("sentiment", "neutral"))
            # Titres + publishers = contenu externe brut → escape_html obligatoire
            # (un « < » brut casserait tout le message, cf. notify/telegram.py).
            title = escape_html(h["title"])
            pub = escape_html(h.get("publisher", "?"))
            lines.append(f"{emo} {title} — <i>{pub}</i>")
    lines.append("")
    lines.append("ℹ️ <i>Détection, pas prédiction. À toi de juger.</i>")
    return "\n".join(lines)


def format_macro_alert(*, event_name: str, minutes: int, when_utc: str, assets: list[str]) -> str:
    # Nom d'event + assets viennent d'une API tierce (FRED…) → escape_html.
    a = "/".join(escape_html(x) for x in (assets or [])) or "?"
    return (
        f"⏰ <b>Alerte macro — {escape_html(event_name)} dans {minutes} min</b>\n"
        f"{when_utc} UTC · impacte {a}\n"
        f"Discipline : pas d'entrée swing ±4h, sizing /2 si tu trades "
        f"(Garde-fou 2-bis)."
    )


def should_alert_risk_flip(current: str | None, previous: str | None) -> bool:
    """Faut-il alerter sur la bascule du régime de risque (ADR-035) ? Pur.

    Alerte uniquement sur une transition qui touche `risk_off` : entrée en
    `risk_off` (le feu passe orange, sizing ÷2) ou sortie de `risk_off` (le
    frein se lève). risk_on ↔ neutral = bruit, pas d'alerte.
    """
    if current not in KNOWN_RISK_STATES or previous not in KNOWN_RISK_STATES:
        return False
    if current == previous:
        return False
    return "risk_off" in (current, previous)


def format_risk_flip_alert(
    *,
    current: str,
    previous: str,
    vix: float | None,
    hy_oas: float | None,
    stress_pct: float | None,
) -> str:
    """Texte de l'alerte bascule risque (pur). Contexte, pas prédiction."""
    into_risk_off = current == "risk_off"
    head = (
        "🔴 <b>Alerte macro — passage en RISK-OFF</b>"
        if into_risk_off
        else f"🟢 <b>Alerte macro — sortie du risk-off</b> (retour {current.replace('_', '-')})"
    )
    lines = [head, f"Régime de risque : {previous.replace('_', '-')} → {current.replace('_', '-')}"]
    detail: list[str] = []
    if vix is not None:
        detail.append(f"VIX {vix:.1f}")
    if hy_oas is not None:
        detail.append(f"spread HY {hy_oas:.2f}%")
    if stress_pct is not None:
        detail.append(f"stress {stress_pct * 100:.0f}ᵉ centile 1 an")
    if detail:
        lines.append(" · ".join(detail))
    if into_risk_off:
        lines.append("Le feu de sécurité du cockpit passe en prudence : sizing ÷2.")
    else:
        lines.append("Le frein risk-off du feu de sécurité se lève.")
    lines.append("ℹ️ <i>Contexte VIX/crédit (ADR-035), pas une prédiction BTC.</i>")
    return "\n".join(lines)


# ---------------- orchestration (IO) ----------------


async def _check_risk_flip(redis: Redis, settings: Settings, *, dry_run: bool) -> str | None:
    """Alerte si le régime de risque (ADR-035) entre ou sort de risk_off.

    Anti-spam : le dernier état connu vit dans Redis (`RISK_STATE_KEY`). Premier
    passage (pas d'état stocké) = amorçage silencieux. On ne persiste le nouvel
    état QUE si l'envoi a réussi (échec transitoire → retenté au cycle suivant) ;
    les flips non alertables (risk_on ↔ neutral) sont persistés directement.
    """
    try:
        raw = await redis.get(MACRO_REGIME_KEY)
        rr = (json.loads(raw) or {}).get("risk_regime") if raw else None
    except Exception as exc:  # noqa: BLE001
        log.warning("alerts.risk_regime_read_error", error=str(exc))
        return None
    current = (rr or {}).get("risk_state")
    if current not in KNOWN_RISK_STATES:
        return None

    try:
        previous = await redis.get(RISK_STATE_KEY)
    except Exception as exc:  # noqa: BLE001
        log.warning("alerts.risk_state_read_error", error=str(exc))
        return None

    if previous is None:
        if not dry_run:
            await redis.set(RISK_STATE_KEY, current, ex=RISK_STATE_TTL_S)
        return None
    if not should_alert_risk_flip(current, previous):
        if current != previous and not dry_run:
            await redis.set(RISK_STATE_KEY, current, ex=RISK_STATE_TTL_S)
        return None

    vix = (rr.get("vix") or {}).get("value")
    hy = (rr.get("hy_oas") or {}).get("value")
    stress = rr.get("stress_percentile")
    text = format_risk_flip_alert(
        current=current,
        previous=previous,
        vix=vix if isinstance(vix, int | float) else None,
        hy_oas=hy if isinstance(hy, int | float) else None,
        stress_pct=stress if isinstance(stress, int | float) else None,
    )
    if dry_run:
        return text
    ok = await send_message(settings.telegram_bot_token, settings.telegram_chat_id, text)
    if ok:
        try:
            await redis.set(RISK_STATE_KEY, current, ex=RISK_STATE_TTL_S)
        except Exception as exc:  # noqa: BLE001
            log.warning("alerts.risk_state_write_error", error=str(exc))
        log.info("alerts.risk_flip_sent", previous=previous, current=current)
    return text if ok else None


async def _check_price_shock(redis: Redis, settings: Settings, *, dry_run: bool) -> str | None:
    """Détecte un choc BTC et envoie l'alerte. Retourne le texte si alerté."""
    async with httpx.AsyncClient() as client:
        try:
            hist = await fetch_btc_history(client, interval="1h", limit=168)
        except Exception as exc:  # noqa: BLE001
            log.warning("alerts.btc_price_error", error=str(exc))
            return None
    now_price, move_pct = price_move_over_window(hist, PRICE_SHOCK_WINDOW_H)
    last_ts = hist[-1][0]
    now_ts = int(last_ts / 1000)

    try:
        raw = await redis.get(ANCHOR_KEY)
        anchor = json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001
        log.warning("alerts.anchor_read_error", error=str(exc))
        anchor = None

    alert, new_anchor = should_alert_shock(move_pct, now_price, now_ts, anchor)
    if not alert:
        return None

    target = datetime.fromtimestamp((last_ts - PRICE_SHOCK_WINDOW_H * 3600 * 1000) / 1000, tz=UTC)
    p0 = find_closest_price(hist, target, max_diff_ms=2 * 3600 * 1000)
    tech = technical_read([p for _, p in hist])
    headlines, _ = await _fetch_headlines_and_climate(redis)
    text = format_shock_alert(
        p0=p0,
        now_price=now_price,
        move_pct=move_pct,
        window_h=PRICE_SHOCK_WINDOW_H,
        tech=tech,
        headlines=headlines,
    )
    if dry_run:
        return text
    ok = await send_message(settings.telegram_bot_token, settings.telegram_chat_id, text)
    if ok:
        try:
            await redis.set(ANCHOR_KEY, json.dumps(new_anchor), ex=ANCHOR_TTL_S)
        except Exception as exc:  # noqa: BLE001
            log.warning("alerts.anchor_write_error", error=str(exc))
        log.info("alerts.shock_sent", move_pct=round(move_pct, 2))
    return text if ok else None


async def _check_macro(
    session_maker: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
    *,
    dry_run: bool,
) -> list[str]:
    """Pré-alerte les events HIGH imminents non encore alertés. Retourne les textes."""
    now_naive = now_utc_naive()
    async with session_maker() as session:
        events = await fetch_upcoming(session, hours=2, importance_filter=["HIGH"], limit=20)
    imminent = imminent_macro(events, now_naive)
    sent_texts: list[str] = []
    for e in imminent:
        key = macro_event_key(e)
        try:
            already = await redis.sismember(MACRO_SENT_KEY, key)
        except Exception as exc:  # noqa: BLE001
            log.warning("alerts.macro_dedup_error", error=str(exc))
            already = False
        if already:
            continue
        minutes = int((e.scheduled_for - now_naive).total_seconds() / 60)
        text = format_macro_alert(
            event_name=e.event_name,
            minutes=minutes,
            when_utc=e.scheduled_for.strftime("%d/%m %H:%M"),
            assets=list(e.assets_impacted or []),
        )
        sent_texts.append(text)
        if dry_run:
            continue
        ok = await send_message(settings.telegram_bot_token, settings.telegram_chat_id, text)
        if ok:
            try:
                await redis.sadd(MACRO_SENT_KEY, key)
                await redis.expire(MACRO_SENT_KEY, MACRO_SENT_TTL_S)
            except Exception as exc:  # noqa: BLE001
                log.warning("alerts.macro_mark_error", error=str(exc))
            # `event_code=` et pas `event=` : `event` est le nom positionnel
            # réservé du bound logger structlog → kwarg `event=` lève « got
            # multiple values for argument 'event' » (bug 2026-06-05).
            log.info("alerts.macro_sent", event_code=e.event_code, minutes=minutes)
    return sent_texts


async def check_and_alert(
    session_maker: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings | None = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Point d'entrée : vérifie choc + macro + risque, envoie les alertes. Ne lève jamais.

    `dry_run` : compose mais n'envoie rien et n'écrit pas Redis (pour tester).
    Retourne {"shock": str|None, "macro": [str, ...], "risk_flip": str|None}.
    """
    settings = settings or get_settings()
    shock = None
    macro: list[str] = []
    risk_flip = None
    try:
        shock = await _check_price_shock(redis, settings, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        log.error("alerts.shock_error", error=str(exc))
    try:
        macro = await _check_macro(session_maker, redis, settings, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        log.error("alerts.macro_error", error=str(exc))
    try:
        risk_flip = await _check_risk_flip(redis, settings, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        log.error("alerts.risk_flip_error", error=str(exc))
    return {"shock": shock, "macro": macro, "risk_flip": risk_flip}


async def _preview() -> None:
    """Dry-run CLI : `python -m tik_core.notify.alerts` (compose sans envoyer)."""
    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import create_async_engine

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        res = await check_and_alert(session_maker, redis, settings, dry_run=True)
        print("=== SHOCK ===")
        print(res["shock"] or "(aucun choc détecté)")
        print("\n=== MACRO ===")
        print("\n---\n".join(res["macro"]) if res["macro"] else "(aucun event imminent)")
        print("\n=== RISK FLIP ===")
        print(res["risk_flip"] or "(pas de bascule de régime de risque)")
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_preview())
