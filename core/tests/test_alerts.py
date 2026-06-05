"""Tests des helpers purs des alertes Telegram (Paquet 50 — étape 2).

Couvre la détection de choc prix, l'anti-spam (ancre + cooldown), la sélection
d'events macro imminents et le formatage. Sans réseau ni DB.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from tik_core.notify.alerts import (
    PRICE_SHOCK_COOLDOWN_S,
    format_macro_alert,
    format_shock_alert,
    imminent_macro,
    macro_event_key,
    price_move_over_window,
    should_alert_shock,
)


def _mk_hist(prices: list[float], base: int = 1_700_000_000_000, step_ms: int = 3_600_000):
    return [(base + i * step_ms, float(p)) for i, p in enumerate(prices)]


# ---------- price_move_over_window ----------


def test_price_move_too_short():
    assert price_move_over_window([(0, 100.0)], 6) == (None, None)


def test_price_move_basic():
    # 7 points horaires : le dernier (index 6) vs 6h avant (index 0) = -3 %.
    prices = [100.0, 100, 100, 100, 100, 100, 97.0]
    now_price, move = price_move_over_window(_mk_hist(prices), 6)
    assert now_price == pytest.approx(97.0)
    assert move == pytest.approx(-3.0)


# ---------- should_alert_shock ----------


def test_no_shock_below_threshold():
    alert, anchor = should_alert_shock(1.5, 70000.0, 1000, None)
    assert alert is False
    assert anchor is None


def test_shock_no_anchor_alerts():
    alert, anchor = should_alert_shock(-3.5, 70000.0, 1000, None)
    assert alert is True
    assert anchor == {"price": 70000.0, "ts": 1000}


def test_shock_dedup_small_move_recent():
    # Choc encore en cours mais prix ~inchangé depuis l'ancre + cooldown non écoulé.
    anchor = {"price": 70000.0, "ts": 1000}
    alert, new = should_alert_shock(-3.2, 69900.0, 1000 + 600, anchor)
    assert alert is False
    assert new == anchor


def test_shock_realerts_after_another_threshold():
    # Le prix a chuté d'un nouveau -3 % depuis l'ancre → ré-alerte.
    anchor = {"price": 70000.0, "ts": 1000}
    alert, new = should_alert_shock(-6.0, 67900.0, 1000 + 600, anchor)
    assert alert is True
    assert new["price"] == pytest.approx(67900.0)


def test_shock_realerts_after_cooldown():
    anchor = {"price": 70000.0, "ts": 1000}
    alert, new = should_alert_shock(-3.2, 69950.0, 1000 + PRICE_SHOCK_COOLDOWN_S + 1, anchor)
    assert alert is True


def test_shock_none_move_no_alert():
    alert, anchor = should_alert_shock(None, None, 1000, None)
    assert alert is False


# ---------- imminent_macro ----------


def _ev(code: str, when: datetime):
    return SimpleNamespace(
        event_code=code, scheduled_for=when, assets_impacted=["BTC"], event_name=code
    )


def test_imminent_macro_window():
    now = datetime(2026, 6, 5, 11, 30)  # naïf UTC
    events = [
        _ev("NFP", datetime(2026, 6, 5, 12, 0)),  # dans 30 min → inclus
        _ev("CPI", datetime(2026, 6, 5, 13, 0)),  # dans 90 min → exclu (lead 60)
        _ev("OLD", datetime(2026, 6, 5, 11, 0)),  # passé → exclu
    ]
    res = imminent_macro(events, now, lead_min=60)
    assert [e.event_code for e in res] == ["NFP"]


def test_macro_event_key_stable():
    e = _ev("NFP", datetime(2026, 6, 5, 12, 30))
    assert macro_event_key(e) == "NFP|2026-06-05T12:30:00"


# ---------- formatage ----------


def test_format_shock_alert():
    text = format_shock_alert(
        p0=74000.0,
        now_price=71000.0,
        move_pct=-4.1,
        window_h=6,
        tech={
            "trend": "sous EMA20 & EMA50 (tendance baissière)",
            "rsi": 28.0,
            "rsi_label": "RSI 28 (proche survente)",
        },
        headlines=[{"title": "Strategy sells BTC", "publisher": "qz.com", "sentiment": "bear"}],
    )
    assert "Alerte BTC — choc de prix" in text
    assert "74,000" in text and "71,000" in text
    assert "Strategy sells BTC" in text
    assert "Détection, pas prédiction" in text


def test_format_macro_alert():
    text = format_macro_alert(
        event_name="Non-Farm Employment Change",
        minutes=30,
        when_utc="05/06 12:30",
        assets=["BTC", "GOLD"],
    )
    assert "Non-Farm Employment Change" in text
    assert "30 min" in text
    assert "Garde-fou 2-bis" in text


# ---------- garde-fou régression : log de succès _check_macro (bug NFP 2026-06-05) ----------


class _StructlogSpy:
    """Logger espion à la signature `(event, **kw)` du bound logger structlog.
    Un MagicMock accepterait `event=` sans broncher et masquerait la collision ;
    ici `info("msg", event=...)` lève bien `TypeError`, comme en prod."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def info(self, event, **kw):  # noqa: ANN001, ANN003
        self.calls.append(("info", event))

    def warning(self, event, **kw):  # noqa: ANN001, ANN003
        self.calls.append(("warning", event))

    def error(self, event, **kw):  # noqa: ANN001, ANN003
        self.calls.append(("error", event))


class _FakeRedis:
    async def sismember(self, key, member):  # noqa: ANN001
        return False

    async def sadd(self, key, *members):  # noqa: ANN001
        return 1

    async def expire(self, key, ttl):  # noqa: ANN001
        return True


class _FakeSessionCtx:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, *exc):  # noqa: ANN002
        return False


def _fake_session_maker():
    return _FakeSessionCtx()


@pytest.mark.asyncio
async def test_check_macro_success_log_does_not_raise(monkeypatch):
    """GUARD jumeau de macro_proximity : `_check_macro` envoie le Telegram +
    marque le dedup, PUIS loggue `alerts.macro_sent`. Si ce log utilise le kwarg
    réservé structlog `event=`, il lève `TypeError` qui remonte (loggé
    `alerts.macro_error` par `check_and_alert`) — constaté en prod le 1er NFP
    2026-06-05. Avec le spy (vraie signature structlog), l'ancien code ferait
    lever `_check_macro` → ce test échouerait."""
    from tik_core.notify import alerts as al

    now = datetime(2026, 6, 5, 11, 30)  # naïf UTC
    ev = _ev("NFP", datetime(2026, 6, 5, 12, 0))  # +30 min → imminent (lead 60)

    async def _fake_fetch_upcoming(session, *args, **kw):  # noqa: ANN001, ANN002
        return [ev]

    async def _fake_send(token, chat, text):  # noqa: ANN001
        return True

    spy = _StructlogSpy()
    monkeypatch.setattr(al, "now_utc_naive", lambda: now)
    monkeypatch.setattr(al, "fetch_upcoming", _fake_fetch_upcoming)
    monkeypatch.setattr(al, "send_message", _fake_send)
    monkeypatch.setattr(al, "log", spy)

    settings = SimpleNamespace(telegram_bot_token="x", telegram_chat_id="y")
    # Ne lève pas (sinon régression bug NFP) :
    texts = await al._check_macro(_fake_session_maker, _FakeRedis(), settings, dry_run=False)

    logged = [event for (_level, event) in spy.calls]
    assert "alerts.macro_sent" in logged, "le log de succès n'a pas été émis proprement"
    assert len(texts) == 1  # un texte d'alerte composé pour le NFP imminent
