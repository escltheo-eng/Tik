"""Tests du client Telegram (notify/telegram.py) — httpx mocké, zéro réseau.

Couvre les fixes de l'audit 2026-07-02 :
- `escape_html` : le contenu externe échappé traverse un serveur Telegram
  simulé strict (400 sur HTML invalide), le contenu brut est refusé ;
- `truncate_html` : troncature à 4096 en préservant un HTML valide (pas de
  tag coupé au milieu, tags ouverts refermés, entité non tronquée) ;
- retry : 429 avec `retry_after` honoré (borné 30 s), timeout/5xx retenté
  UNE fois après 2 s, échec final → False (best-effort, jamais d'exception).

Le transport httpx est mocké via httpx.MockTransport (pattern
test_cftc_cot_ingester) ; `telegram._sleep` est remplacé par un espion pour
ne pas attendre réellement les délais de retry.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest

from tik_core.notify import telegram
from tik_core.notify.telegram import (
    RETRY_AFTER_MAX_S,
    RETRY_NETWORK_DELAY_S,
    TELEGRAM_MAX_LEN,
    TRUNCATION_MARKER,
    escape_html,
    send_message,
    truncate_html,
)

TOKEN = "123:abc"
CHAT_ID = "42"

# Tags autorisés par le faux serveur Telegram strict (sous-ensemble réel).
_ALLOWED_TAG_RE = re.compile(r"</?(b|strong|i|em|u|s|code|pre|a)(\s[^<>]*)?>")


def _ok_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})


def _strict_telegram(request: httpx.Request) -> httpx.Response:
    """Simule le parseur HTML de Telegram : 400 si un « < » ou « > » brut
    subsiste hors des tags autorisés (comportement réel de sendMessage)."""
    text = json.loads(request.content)["text"]
    stripped = _ALLOWED_TAG_RE.sub("", text)
    if "<" in stripped or ">" in stripped:
        return httpx.Response(
            400,
            json={"ok": False, "description": "Bad Request: can't parse entities"},
        )
    return _ok_response(request)


class _ScriptedHandler:
    """Handler MockTransport qui rejoue une séquence de réponses/exceptions."""

    def __init__(self, steps: list):
        self.steps = list(steps)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert self.steps, "appel HTTP inattendu (séquence épuisée)"
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def patch_transport(monkeypatch):
    """Force send_message à passer par un httpx.MockTransport donné."""

    def _patch(handler):
        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient

        def factory(**kwargs):
            kwargs["transport"] = transport
            return real_client(**kwargs)

        monkeypatch.setattr(telegram.httpx, "AsyncClient", factory)
        return transport

    return _patch


@pytest.fixture
def sleep_spy(monkeypatch):
    """Remplace telegram._sleep : enregistre les délais sans attendre."""
    calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        calls.append(delay)

    monkeypatch.setattr(telegram, "_sleep", fake_sleep)
    return calls


# ---------- escape_html ----------


def test_escape_html_replaces_lt_gt_amp_only():
    assert escape_html("Bitcoin <$60k & <b>rising</b>") == (
        "Bitcoin &lt;$60k &amp; &lt;b&gt;rising&lt;/b&gt;"
    )
    # Guillemets non touchés (contenu interpolé comme texte, pas en attribut).
    assert escape_html('l\'or "safe haven"') == 'l\'or "safe haven"'


def test_escape_html_coerces_non_str():
    assert escape_html(60000) == "60000"


# ---------- succès nominal ----------


async def test_send_message_success(patch_transport):
    handler = _ScriptedHandler([httpx.Response(200, json={"ok": True})])
    patch_transport(handler)
    assert await send_message(TOKEN, CHAT_ID, "<b>Briefing Tik</b>") is True
    assert len(handler.requests) == 1
    payload = json.loads(handler.requests[0].content)
    assert payload["chat_id"] == CHAT_ID
    assert payload["parse_mode"] == "HTML"
    assert payload["text"] == "<b>Briefing Tik</b>"


async def test_send_message_no_credentials_returns_false():
    assert await send_message("", CHAT_ID, "hello") is False
    assert await send_message(TOKEN, "", "hello") is False


# ---------- échappement HTML vs serveur Telegram strict ----------


async def test_escaped_external_title_passes_strict_server(patch_transport):
    """Un titre externe avec < et & échappé via escape_html → accepté (200)."""
    patch_transport(_strict_telegram)
    title = escape_html("Bitcoin <$60k & falling")
    text = f"📰 {title} — <i>coindesk</i>"
    assert await send_message(TOKEN, CHAT_ID, text) is True


async def test_raw_external_title_rejected_by_strict_server(patch_transport):
    """Sans échappement, le même titre fait perdre le message entier (400)."""
    handler = _ScriptedHandler(
        [
            httpx.Response(
                400,
                json={"ok": False, "description": "Bad Request: can't parse entities"},
            )
        ]
    )
    patch_transport(handler)
    assert await send_message(TOKEN, CHAT_ID, "📰 Bitcoin <$60k — <i>coindesk</i>") is False
    # 400 = erreur non transitoire → PAS de retry.
    assert len(handler.requests) == 1


# ---------- 429 : retry_after honoré ----------


async def test_429_retry_after_honored_then_success(patch_transport, sleep_spy):
    handler = _ScriptedHandler(
        [
            httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 7}}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    patch_transport(handler)
    assert await send_message(TOKEN, CHAT_ID, "hello") is True
    assert len(handler.requests) == 2
    assert sleep_spy == [7.0]


async def test_429_retry_after_capped_at_30s(patch_transport, sleep_spy):
    handler = _ScriptedHandler(
        [
            httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 120}}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    patch_transport(handler)
    assert await send_message(TOKEN, CHAT_ID, "hello") is True
    assert sleep_spy == [RETRY_AFTER_MAX_S]


async def test_429_without_retry_after_uses_default_delay(patch_transport, sleep_spy):
    handler = _ScriptedHandler(
        [
            httpx.Response(429, json={"ok": False}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    patch_transport(handler)
    assert await send_message(TOKEN, CHAT_ID, "hello") is True
    assert sleep_spy == [RETRY_NETWORK_DELAY_S]


async def test_429_twice_gives_up_false(patch_transport, sleep_spy):
    handler = _ScriptedHandler(
        [
            httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 3}}),
            httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 3}}),
        ]
    )
    patch_transport(handler)
    assert await send_message(TOKEN, CHAT_ID, "hello") is False
    assert len(handler.requests) == 2  # un seul retry, pas plus
    assert sleep_spy == [3.0]


# ---------- timeout / 5xx : un retry à 2 s ----------


async def test_timeout_then_success_retries_once(patch_transport, sleep_spy):
    handler = _ScriptedHandler(
        [httpx.ConnectTimeout("timeout"), httpx.Response(200, json={"ok": True})]
    )
    patch_transport(handler)
    assert await send_message(TOKEN, CHAT_ID, "hello") is True
    assert len(handler.requests) == 2
    assert sleep_spy == [RETRY_NETWORK_DELAY_S]


async def test_5xx_then_success_retries_once(patch_transport, sleep_spy):
    handler = _ScriptedHandler(
        [httpx.Response(502, text="Bad Gateway"), httpx.Response(200, json={"ok": True})]
    )
    patch_transport(handler)
    assert await send_message(TOKEN, CHAT_ID, "hello") is True
    assert len(handler.requests) == 2
    assert sleep_spy == [RETRY_NETWORK_DELAY_S]


async def test_timeout_twice_returns_false_never_raises(patch_transport, sleep_spy):
    handler = _ScriptedHandler([httpx.ConnectTimeout("t1"), httpx.ReadTimeout("t2")])
    patch_transport(handler)
    assert await send_message(TOKEN, CHAT_ID, "hello") is False
    assert len(handler.requests) == 2


async def test_5xx_twice_returns_false(patch_transport, sleep_spy):
    handler = _ScriptedHandler([httpx.Response(500, text="boom"), httpx.Response(500, text="boom")])
    patch_transport(handler)
    assert await send_message(TOKEN, CHAT_ID, "hello") is False
    assert len(handler.requests) == 2


# ---------- troncature 4096 ----------


def test_truncate_short_text_unchanged():
    assert truncate_html("hello <b>world</b>") == "hello <b>world</b>"


def test_truncate_plain_text_at_limit():
    out = truncate_html("x" * 5000)
    assert len(out) <= TELEGRAM_MAX_LEN
    assert out.endswith(TRUNCATION_MARKER)
    assert out.startswith("xxx")


def test_truncate_never_cuts_mid_tag():
    # Le budget de coupe tombe en plein milieu de « <b>… » → recule avant « < ».
    text = "x" * 4080 + "<b>" + "y" * 100 + "</b>"
    out = truncate_html(text)
    assert len(out) <= TELEGRAM_MAX_LEN
    assert out.endswith(TRUNCATION_MARKER)
    assert "<" not in out.replace(TRUNCATION_MARKER, "")  # aucun tag résiduel cassé


def test_truncate_closes_open_tags():
    text = "<b>" + "x" * 5000 + "</b>"
    out = truncate_html(text)
    assert len(out) <= TELEGRAM_MAX_LEN
    assert out.startswith("<b>")
    assert "</b>" in out  # tag refermé pour que Telegram accepte le HTML
    assert out.endswith(TRUNCATION_MARKER)


def test_truncate_closes_nested_tags_in_order():
    text = "<b><i>" + "x" * 5000
    out = truncate_html(text)
    assert len(out) <= TELEGRAM_MAX_LEN
    assert "</i></b>" in out  # refermeture en ordre inverse d'ouverture


def test_truncate_does_not_cut_entity():
    # Le budget tombe au milieu de « &amp; » → recule avant le « & ».
    text = "x" * 4083 + "&amp;" + "y" * 100
    out = truncate_html(text)
    assert len(out) <= TELEGRAM_MAX_LEN
    body = out.removesuffix(TRUNCATION_MARKER)
    assert "&" not in body  # pas d'entité tronquée type « &am »


async def test_send_message_truncates_before_sending(patch_transport):
    handler = _ScriptedHandler([httpx.Response(200, json={"ok": True})])
    patch_transport(handler)
    assert await send_message(TOKEN, CHAT_ID, "<b>t</b> " + "z" * 6000) is True
    sent = json.loads(handler.requests[0].content)["text"]
    assert len(sent) <= TELEGRAM_MAX_LEN
    assert sent.endswith(TRUNCATION_MARKER)
