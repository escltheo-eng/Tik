"""Client Telegram Bot API — notifications sortantes (briefing + alertes).

Outbound only, best-effort : toute erreur réseau/API est loggée mais JAMAIS
propagée (un échec d'envoi ne doit jamais casser un cycle scheduler). Cohérent
avec le pattern best-effort du projet (`headlines_repo.persist_headlines`,
`macro_events_repo.upsert_many`).

Robustesse (audit 2026-07-02) :
- `escape_html` : à appliquer sur TOUT contenu externe (titres de news, noms
  d'événements…) avant interpolation dans un message parse_mode=HTML — un « < »
  brut fait répondre 400 à Telegram et le message ENTIER est perdu.
- Troncature à 4096 caractères (limite dure de sendMessage) en préservant un
  HTML valide.
- 1 retry sur 429 (délai `retry_after` de Telegram, borné à 30 s) et 1 retry
  sur timeout/5xx (2 s).

Le bot est créé par l'utilisatrice via @BotFather ; le token + chat_id vivent
dans core/.env (TIK_TELEGRAM_BOT_TOKEN / TIK_TELEGRAM_CHAT_ID).
"""

from __future__ import annotations

import asyncio
import html
import re

import httpx
import structlog

log = structlog.get_logger()

TELEGRAM_API_TPL = "https://api.telegram.org/bot{token}/{method}"

# Limite dure de l'API Telegram pour le champ `text` de sendMessage.
TELEGRAM_MAX_LEN = 4096
# Marqueur ajouté en fin de message quand il a dû être tronqué.
TRUNCATION_MARKER = "… [tronqué]"
# Borne haute du délai accepté depuis `parameters.retry_after` d'un 429.
RETRY_AFTER_MAX_S = 30.0
# Délai fixe avant le retry unique sur timeout / erreur réseau / 5xx.
RETRY_NETWORK_DELAY_S = 2.0

# Tag HTML façon Telegram : <b>, </i>, <a href="…">… (pas de self-closing).
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)(?:\s[^<>]*)?>")

# Indirection testable : les tests remplacent `_sleep` pour ne pas attendre.
_sleep = asyncio.sleep


def escape_html(value: object) -> str:
    """Échappe du contenu EXTERNE avant interpolation dans un message HTML.

    À appliquer sur tout ce qui vient d'une API tierce (titre de news, nom
    d'événement macro, publisher…) : un « < » brut (ex. « Bitcoin <$60k »)
    fait répondre 400 à Telegram → le message entier (briefing du créneau,
    alerte) serait perdu. Seuls `< > &` sont remplacés (exigence Telegram) ;
    les guillemets restent tels quels (le contenu est interpolé comme texte,
    jamais dans un attribut). Helper public : réutilisable par tout code qui
    compose du HTML Telegram (ex. breaking_news_ingester).
    """
    return html.escape(str(value), quote=False)


def _open_tags(fragment: str) -> list[str]:
    """Liste ordonnée des tags HTML encore ouverts dans `fragment` (pur)."""
    stack: list[str] = []
    for m in _TAG_RE.finditer(fragment):
        closing, name = m.group(1), m.group(2).lower()
        if closing:
            if stack and stack[-1] == name:
                stack.pop()
        else:
            stack.append(name)
    return stack


def truncate_html(text: str, max_len: int = TELEGRAM_MAX_LEN) -> str:
    """Tronque `text` à `max_len` caractères en gardant un HTML valide.

    Approche simple (documentée — audit 2026-07-02) :
    1. coupe au budget (limite − marqueur) ;
    2. si la coupe tombe au milieu d'un tag (« < » jamais refermé par « > »),
       recule la coupe juste avant ce « < » ; idem pour une entité HTML
       coupée en plein milieu (« &am… » sans « ; ») ;
    3. referme les tags encore ouverts (<b>, <i>…) pour que le parseur
       Telegram accepte le message, puis ajoute le marqueur « … [tronqué] » ;
    4. les refermetures ajoutant des caractères, re-vérifie la longueur et
       resserre le budget si nécessaire (boucle).
    """
    if len(text) <= max_len:
        return text
    budget = max_len - len(TRUNCATION_MARKER)
    while budget > 0:
        cut = text[:budget]
        # Coupe au milieu d'un tag ? (« < » ouvert après le dernier « > »)
        lt = cut.rfind("<")
        if lt != -1 and cut.rfind(">") < lt:
            cut = cut[:lt]
        # Coupe au milieu d'une entité ? (« & » récent sans « ; » derrière)
        amp = cut.rfind("&")
        if amp != -1 and ";" not in cut[amp:] and len(cut) - amp <= 8:
            cut = cut[:amp]
        closings = "".join(f"</{name}>" for name in reversed(_open_tags(cut)))
        candidate = cut + closings + TRUNCATION_MARKER
        if len(candidate) <= max_len:
            return candidate
        budget -= len(candidate) - max_len
    # Filet théorique (max_len minuscule) : au pire, le marqueur seul.
    return TRUNCATION_MARKER[:max_len]


def _retry_after_s(response: httpx.Response) -> float:
    """Extrait `parameters.retry_after` d'un 429 Telegram (borné, défaut 2 s)."""
    try:
        raw = (response.json().get("parameters") or {}).get("retry_after")
        delay = float(raw)
    except Exception:  # noqa: BLE001 — JSON absent/malformé → délai par défaut
        return RETRY_NETWORK_DELAY_S
    return max(0.0, min(delay, RETRY_AFTER_MAX_S))


async def _post_with_retry(client: httpx.AsyncClient, url: str, payload: dict) -> bool:
    """POST vers Telegram avec au plus UN retry. Retourne True si succès.

    - 429 → relit `retry_after` du JSON, attend (borné 30 s), retente 1 fois ;
    - timeout / erreur réseau / 5xx → attend 2 s, retente 1 fois ;
    - toute autre erreur (400…) → log + False immédiat (retenter est inutile).
    """
    for attempt in (1, 2):
        try:
            r = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            if attempt == 1:
                log.warning("telegram.send.retry", reason="network", error=str(exc))
                await _sleep(RETRY_NETWORK_DELAY_S)
                continue
            log.warning("telegram.send.error", error=str(exc))
            return False
        if r.is_success:
            return True
        if attempt == 1 and r.status_code == 429:
            delay = _retry_after_s(r)
            log.warning("telegram.send.retry", reason="429", retry_after_s=delay)
            await _sleep(delay)
            continue
        if attempt == 1 and r.status_code >= 500:
            log.warning("telegram.send.retry", reason=str(r.status_code))
            await _sleep(RETRY_NETWORK_DELAY_S)
            continue
        log.warning("telegram.send.error", status=r.status_code, body=r.text[:200])
        return False
    return False


async def send_message(
    token: str,
    chat_id: str,
    text: str,
    *,
    timeout_s: float = 15.0,
) -> bool:
    """Envoie un message texte via l'API Telegram Bot. Retourne True si OK.

    `text` accepte du HTML simple (parse_mode=HTML) : <b>gras</b>,
    <i>italique</i>, <a href="...">lien</a>. Le contenu EXTERNE doit être
    passé par `escape_html` en amont (les formatters briefing/alerts le font).
    Le texte est tronqué à 4096 caractères (limite API) via `truncate_html`.
    Best-effort : log warning + return False sur credentials manquants ou
    échec final (après 1 retry sur 429/timeout/5xx) — ne lève jamais.
    """
    if not token or not chat_id:
        log.warning("telegram.send.skipped_no_credentials")
        return False
    url = TELEGRAM_API_TPL.format(token=token, method="sendMessage")
    payload = {
        "chat_id": chat_id,
        "text": truncate_html(text),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            return await _post_with_retry(client, url, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram.send.error", error=str(exc))
        return False


async def get_chat_id(token: str, *, timeout_s: float = 15.0) -> str | None:
    """Récupère le chat_id du dernier message reçu par le bot (via getUpdates).

    Utilitaire one-shot : après que l'utilisatrice a fait /start sur son bot,
    lit getUpdates et renvoie le chat.id du message le plus récent. À stocker
    ensuite dans TIK_TELEGRAM_CHAT_ID. Retourne None si aucun message trouvé.
    """
    url = TELEGRAM_API_TPL.format(token=token, method="getUpdates")
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram.get_chat_id.error", error=str(exc))
        return None
    results = data.get("result") or []
    for update in reversed(results):
        msg = update.get("message") or update.get("channel_post") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is not None:
            return str(cid)
    return None
