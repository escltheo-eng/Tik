"""Briefing du matin — synthèse de contexte envoyée par Telegram.

Compose un message court (événements macro HIGH des prochaines 24 h +
variation BTC/or + drapeau « casse le plus bas » + titres clés) à partir de
ce que Tik a déjà : calendrier macro (ADR-017/020), prix Binance/Yahoo, titres
OSINT agrégés (Phase A.1). Envoyé 3×/jour par le scheduler à des heures calées
sur les matins Europe / Amériques / Asie.

**Cadre honnête (go/no-go NO-GO, cf. CLAUDE.md)** : Tik n'a PAS d'edge de
prédiction. Ce briefing est un outil de **contexte et de discipline**, pas un
signal directionnel. Il prévient AVANT les événements programmés (« les
puissants » = banques centrales, NFP, CPI, FOMC) et CONTEXTUALISE l'état du
marché — il ne dit jamais « ça va monter/descendre ».

Architecture : helpers purs (`summarize_price`, `briefing_window_label`,
`format_briefing`, formatters) testables sans réseau + 2 fonctions async qui
font l'IO (`gather_briefing_data`, `send_briefing`).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd
import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Réutilisation des helpers purs de l'endpoint headlines (Phase A.1) — même
# logique d'extraction/dédup/tri que la carte dashboard, pas de duplication.
from tik_core.api.headlines import (
    NEWS_SOURCE_KEYS,
    _finalize_headlines,
    _iter_headlines_from_payload,
)
from tik_core.config import Settings, get_settings
from tik_core.notify.telegram import send_message
from tik_core.scoring.indicators import ema, rsi
from tik_core.scoring.swing_engine import SOURCE_SCORES
from tik_core.scripts.backtest import (
    fetch_btc_history,
    fetch_gold_history,
    find_closest_price,
)
from tik_core.storage.macro_events_repo import fetch_upcoming
from tik_core.utils.time import now_utc, now_utc_naive

log = structlog.get_logger()

# Seuil « au plus bas » : within 1 % du plus bas de la fenêtre observée.
NEAR_LOW_PCT = 0.01
# Nombre de titres clés inclus dans le briefing.
N_HEADLINES = 3
# Positionnement dérivés BTC (shadow ADR-023, observation — pas un signal).
DERIV_REDIS_KEY = "tik.deriv.binance.btc"
# Divergence retail vs top traders jugée notable au-delà de 5 points de %.
DERIV_DIVERGENCE_PCT = 0.05


def _dt_from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def summarize_price(history: list[tuple[int, float]]) -> dict | None:
    """Résume une série de klines [(ts_ms, close)] → variation + fourchette.

    Pur (aucune IO). Retourne None si l'historique est trop court.

    - `now` : dernier close
    - `chg_24h` : variation % vs ~24 h avant (None si introuvable dans la marge)
    - `chg_span` : variation % vs le 1er point de la fenêtre (~durée span_h)
    - `low` / `high` : extrêmes de la fenêtre
    - `near_low` : True si `now` est à ≤ 1 % du plus bas de la fenêtre
    """
    if len(history) < 2:
        return None
    last_ts, now_price = history[-1]
    closes = [p for _, p in history]
    first_ts, first_price = history[0]

    target_24h = _dt_from_ms(last_ts - 24 * 3600 * 1000)
    p24 = find_closest_price(history, target_24h, max_diff_ms=3 * 3600 * 1000)

    low = min(closes)
    high = max(closes)
    span_h = round((last_ts - first_ts) / 3_600_000)
    return {
        "now": now_price,
        "chg_24h": round((now_price / p24 - 1) * 100, 2) if p24 else None,
        "chg_span": round((now_price / first_price - 1) * 100, 2) if first_price else None,
        "span_h": span_h,
        "low": low,
        "high": high,
        "near_low": bool(low > 0 and (now_price - low) / low <= NEAR_LOW_PCT),
    }


def technical_read(closes: list[float]) -> dict | None:
    """Lecture technique BTC (pur) : tendance EMA20/50 + RSI14.

    Réutilise les indicateurs `ema`/`rsi` du moteur (scoring/indicators).
    Informatif uniquement — depuis ADR-018 la technique ne décide PAS de la
    direction (poids 0.0), mais reste un repère de contexte pour l'humain.
    Retourne None si < 50 points (EMA50 indéfinie) ou RSI indéfini.
    """
    if len(closes) < 50:
        return None
    s = pd.Series(closes, dtype="float64")
    ema20 = float(ema(s, 20).iloc[-1])
    ema50 = float(ema(s, 50).iloc[-1])
    rsi_val = rsi(s, 14).iloc[-1]
    if pd.isna(rsi_val):
        return None
    rsi14 = float(rsi_val)
    now = closes[-1]
    if now < ema20 and now < ema50:
        trend = "sous EMA20 & EMA50 (tendance baissière)"
    elif now > ema20 and now > ema50:
        trend = "au-dessus EMA20 & EMA50 (tendance haussière)"
    else:
        trend = "entre EMA20 et EMA50 (indécis)"
    if rsi14 < 30:
        rsi_label = f"RSI {rsi14:.0f} (proche survente)"
    elif rsi14 > 70:
        rsi_label = f"RSI {rsi14:.0f} (proche surachat)"
    else:
        rsi_label = f"RSI {rsi14:.0f}"
    return {"trend": trend, "rsi": rsi14, "rsi_label": rsi_label}


def climate_from_headlines(headlines: list[dict]) -> dict:
    """Agrège le climat de sentiment d'une liste de titres (pur).

    Compte bull/bear/neutral et déduit un tilt simple (`tilt` None si vide).
    """
    bull = sum(1 for h in headlines if h.get("sentiment") == "bull")
    bear = sum(1 for h in headlines if h.get("sentiment") == "bear")
    neutral = sum(1 for h in headlines if h.get("sentiment") == "neutral")
    total = bull + bear + neutral
    if total == 0:
        tilt = None
    elif bear >= max(1, round(bull * 1.5)):
        tilt = "baissier 🔴"
    elif bull >= max(1, round(bear * 1.5)):
        tilt = "haussier 🟢"
    else:
        tilt = "mitigé ⚪"
    return {"bull": bull, "bear": bear, "neutral": neutral, "tilt": tilt}


def _funding_label(funding_pct: float) -> str:
    """Qualifie un funding rate (en %/8h) : neutre / qui paie qui / élevé."""
    a = abs(funding_pct)
    if a < 0.01:
        return "neutre"
    side = "longs paient" if funding_pct > 0 else "shorts paient"
    return f"{side}, élevé" if a >= 0.05 else side


def summarize_derivatives(snap: dict | None) -> dict | None:
    """Résume le positionnement dérivés BTC (pur). None si rien d'exploitable.

    Lecture honnête : funding (qui paie qui), positionnement long retail vs top
    traders, et si les deux divergent (signal contrarian classique). C'est de
    l'OBSERVATION de marché, pas un signal Tik (shadow ADR-023).
    """
    if not isinstance(snap, dict):
        return None
    funding = snap.get("funding_rate")
    oi_usd = snap.get("open_interest_usd")
    long_g = snap.get("long_account_global")
    long_t = snap.get("long_account_top")
    has_funding = isinstance(funding, int | float)
    has_pos = isinstance(long_g, int | float)
    if not has_funding and not has_pos:
        return None
    funding_pct = funding * 100 if has_funding else None
    divergent = None
    if has_pos and isinstance(long_t, int | float):
        divergent = abs(long_g - long_t) >= DERIV_DIVERGENCE_PCT
    return {
        "funding_pct": funding_pct,
        "funding_label": _funding_label(funding_pct) if funding_pct is not None else None,
        "oi_usd": oi_usd if isinstance(oi_usd, int | float) else None,
        "long_pct_retail": long_g * 100 if has_pos else None,
        "long_pct_top": long_t * 100 if isinstance(long_t, int | float) else None,
        "divergent": divergent,
    }


def _fmt_derivatives_lines(deriv: dict | None) -> list[str]:
    """Section briefing « positionnement dérivés » (vide si pas de donnée)."""
    if not deriv:
        return []
    lines = ["⚙️ <b>Positionnement dérivés BTC</b> <i>(observation, pas un signal)</i>"]
    parts: list[str] = []
    if deriv.get("funding_pct") is not None:
        parts.append(f"funding {deriv['funding_pct']:+.3f}%/8h ({deriv['funding_label']})")
    if deriv.get("oi_usd") is not None:
        parts.append(f"OI {deriv['oi_usd'] / 1e9:.1f} Mds$")
    if parts:
        lines.append("• " + " · ".join(parts))
    if deriv.get("long_pct_retail") is not None:
        div = deriv.get("divergent")
        tail = (
            " (alignés)"
            if div is False
            else " (divergent ⚠)"
            if div is True
            else ""
        )
        top = (
            f" / {deriv['long_pct_top']:.0f}% top"
            if deriv.get("long_pct_top") is not None
            else ""
        )
        lines.append(f"• longs {deriv['long_pct_retail']:.0f}% retail{top}{tail}")
    return lines


def briefing_window_label(now: datetime) -> str:
    """Libellé de la fenêtre horaire selon l'heure UTC courante."""
    h = now.hour
    if 3 <= h < 9:
        return "🌍 Matin Europe"
    if 9 <= h < 16:
        return "🇺🇸 Matin Amériques"
    return "🌏 Matin Asie"


def _fmt_hours_until(scheduled_naive: datetime, now_naive: datetime) -> str:
    """Formate l'attente jusqu'à un event (datetimes naïfs UTC)."""
    delta_min = (scheduled_naive - now_naive).total_seconds() / 60
    if delta_min < 0:
        return "en cours"
    if delta_min < 60:
        return f"dans {int(delta_min)} min"
    h = int(delta_min // 60)
    m = int(delta_min % 60)
    return f"dans {h}h{m:02d}"


def _sentiment_emoji(sentiment: str) -> str:
    return {"bull": "🟢", "bear": "🔴"}.get(sentiment, "⚪")


def _fmt_price_line(label: str, summary: dict | None, currency: str = "$") -> str:
    """Une ligne marché : prix + variations + drapeau au plus bas."""
    if summary is None:
        return f"• <b>{label}</b> : donnée indisponible"
    now = summary["now"]
    chg24 = summary["chg_24h"]
    chg_span = summary["chg_span"]
    span_h = summary["span_h"]
    chg24_s = f"24h {chg24:+.1f}%" if chg24 is not None else "24h n/a"
    span_d = max(1, round(span_h / 24))
    chg_span_s = f"{span_d}j {chg_span:+.1f}%" if chg_span is not None else ""
    flag = " ⚠️ <b>au plus bas</b>" if summary["near_low"] else ""
    parts = " · ".join(p for p in [chg24_s, chg_span_s] if p)
    return f"• <b>{label}</b> : {now:,.0f}{currency} — {parts}{flag}"


def format_briefing(
    *,
    window: str,
    now: datetime,
    btc: dict | None,
    gold: dict | None,
    tech: dict | None,
    climate: dict | None,
    events: list[dict],
    headlines: list[dict],
    deriv: dict | None = None,
) -> str:
    """Assemble le texte HTML du briefing (pur, testable sans IO).

    `events` : liste de dicts {event_name, hours_until_str, assets, when_utc}.
    `headlines` : liste de dicts {title, publisher, sentiment}.
    `deriv` : résumé positionnement dérivés BTC (summarize_derivatives) ou None.
    """
    lines: list[str] = []
    lines.append(f"{window} — <b>Briefing Tik</b>")
    lines.append(f"<i>{now:%d/%m %H:%M} UTC</i>")
    lines.append("")

    # --- Macro à venir ---
    lines.append("📅 <b>Macro HIGH — prochaines 24h</b>")
    if events:
        for ev in events:
            assets = "/".join(ev.get("assets") or []) or "?"
            lines.append(
                f"• <b>{ev['event_name']}</b> — {ev['hours_until_str']} "
                f"({assets}) · {ev['when_utc']} UTC"
            )
    else:
        lines.append("• Aucun événement HIGH programmé. Marché « libre ».")
    lines.append("")

    # --- Marché ---
    lines.append("📊 <b>Marché (BTC / Or)</b>")
    lines.append(_fmt_price_line("BTC", btc))
    lines.append(_fmt_price_line("Or", gold))
    lines.append("")

    # --- Lecture rapide (technique + climat news, déterministe) ---
    if tech or (climate and climate.get("tilt")):
        lines.append("🧭 <b>Lecture rapide (BTC)</b>")
        if tech:
            lines.append(f"• Technique : {tech['trend']} · {tech['rsi_label']}")
        if climate and climate.get("tilt"):
            lines.append(
                f"• Climat news : {climate['tilt']} "
                f"({climate['bear']} baissiers / {climate['bull']} haussiers)"
            )
        lines.append("")

    # --- Titres ---
    if headlines:
        lines.append("📰 <b>Titres clés (BTC)</b>")
        for h in headlines:
            emo = _sentiment_emoji(h.get("sentiment", "neutral"))
            pub = h.get("publisher") or "?"
            lines.append(f"{emo} {h['title']} — <i>{pub}</i>")
        lines.append("")

    # --- Positionnement dérivés BTC (shadow ADR-023, observation) ---
    deriv_lines = _fmt_derivatives_lines(deriv)
    if deriv_lines:
        lines.extend(deriv_lines)
        lines.append("")

    # --- Pied de page discipline ---
    lines.append(
        "ℹ️ <i>Contexte, pas prédiction (Tik n'a pas d'edge directionnel). "
        "Discipline : sizing 1 %, BTC seulement, veracity ≥ 85 %.</i>"
    )
    return "\n".join(lines)


async def _fetch_headlines_and_climate(redis: Redis) -> tuple[list[dict], dict]:
    """Lit les titres BTC récents + le climat de sentiment agrégé (helpers Phase A.1).

    Retourne (top N titres triés crédibilité×récence, climat agrégé sur TOUS les
    titres de la fenêtre 24h — pas seulement le top N).
    """
    cutoff = now_utc() - timedelta(hours=24)
    merged: list[dict] = []
    for source_id, key_tpl in NEWS_SOURCE_KEYS:
        key = key_tpl.format(entity="btc")
        try:
            raw = await redis.get(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("briefing.headlines_redis_error", source=source_id, error=str(exc))
            continue
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        credibility = SOURCE_SCORES.get(source_id, 0.70)
        merged.extend(_iter_headlines_from_payload(payload, source_id, credibility, cutoff))
    top = _finalize_headlines(merged, "credibility_recency", N_HEADLINES, now_utc())
    return top, climate_from_headlines(merged)


async def gather_briefing_data(session: AsyncSession, redis: Redis) -> dict:
    """Rassemble toutes les données du briefing (IO : DB + Binance/Yahoo + Redis)."""
    now = now_utc()
    now_naive = now_utc_naive()

    # Macro HIGH prochaines 24h
    rows = await fetch_upcoming(session, hours=24, importance_filter=["HIGH"], limit=10)
    events = [
        {
            "event_name": r.event_name,
            "hours_until_str": _fmt_hours_until(r.scheduled_for, now_naive),
            "assets": list(r.assets_impacted or []),
            "when_utc": r.scheduled_for.strftime("%d/%m %H:%M"),
        }
        for r in rows
    ]

    # Prix (best-effort, indépendants : un échec n'empêche pas l'autre)
    btc = gold = tech = None
    btc_hist: list[tuple[int, float]] = []
    async with httpx.AsyncClient() as client:
        try:
            btc_hist = await fetch_btc_history(client, interval="1h", limit=168)
            btc = summarize_price(btc_hist)
        except Exception as exc:  # noqa: BLE001
            log.warning("briefing.btc_price_error", error=str(exc))
        try:
            gold_hist = await fetch_gold_history(client, interval="1h", range_param="5d")
            gold = summarize_price(gold_hist)
        except Exception as exc:  # noqa: BLE001
            log.warning("briefing.gold_price_error", error=str(exc))

    if btc_hist:
        tech = technical_read([p for _, p in btc_hist])

    headlines, climate = await _fetch_headlines_and_climate(redis)

    # Positionnement dérivés BTC (shadow, observation) — best-effort.
    deriv = None
    try:
        raw_deriv = await redis.get(DERIV_REDIS_KEY)
        if raw_deriv:
            deriv = summarize_derivatives(json.loads(raw_deriv))
    except Exception as exc:  # noqa: BLE001
        log.warning("briefing.derivatives_error", error=str(exc))

    return {
        "window": briefing_window_label(now),
        "now": now,
        "btc": btc,
        "gold": gold,
        "tech": tech,
        "climate": climate,
        "events": events,
        "headlines": headlines,
        "deriv": deriv,
    }


async def compose_briefing(session: AsyncSession, redis: Redis) -> str:
    """Compose le texte complet du briefing (IO + formatage)."""
    data = await gather_briefing_data(session, redis)
    return format_briefing(**data)


async def send_briefing(
    session_maker: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings | None = None,
) -> bool:
    """Compose + envoie le briefing via Telegram. Best-effort, ne lève jamais.

    Retourne True si l'envoi Telegram a réussi, False sinon (credentials
    manquants, erreur réseau, ou exception en cours de composition).
    """
    settings = settings or get_settings()
    try:
        async with session_maker() as session:
            text = await compose_briefing(session, redis)
    except Exception as exc:  # noqa: BLE001
        log.error("briefing.compose_error", error=str(exc))
        return False
    ok = await send_message(settings.telegram_bot_token, settings.telegram_chat_id, text)
    log.info("briefing.sent", ok=ok)
    return ok


async def _preview() -> None:
    """Aperçu CLI : compose et imprime le briefing sans l'envoyer.

    Usage : `python -m tik_core.notify.briefing`
    """
    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import create_async_engine

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with session_maker() as session:
            text = await compose_briefing(session, redis)
        print(text)
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_preview())
