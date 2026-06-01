"""Client Telegram Bot API — notifications sortantes (briefing + alertes).

Outbound only, best-effort : toute erreur réseau/API est loggée mais JAMAIS
propagée (un échec d'envoi ne doit jamais casser un cycle scheduler). Cohérent
avec le pattern best-effort du projet (`headlines_repo.persist_headlines`,
`macro_events_repo.upsert_many`).

Le bot est créé par l'utilisatrice via @BotFather ; le token + chat_id vivent
dans core/.env (TIK_TELEGRAM_BOT_TOKEN / TIK_TELEGRAM_CHAT_ID).
"""

from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger()

TELEGRAM_API_TPL = "https://api.telegram.org/bot{token}/{method}"


async def send_message(
    token: str,
    chat_id: str,
    text: str,
    *,
    timeout_s: float = 15.0,
) -> bool:
    """Envoie un message texte via l'API Telegram Bot. Retourne True si OK.

    `text` accepte du HTML simple (parse_mode=HTML) : <b>gras</b>,
    <i>italique</i>, <a href="...">lien</a>. Best-effort : log warning +
    return False sur credentials manquants ou erreur réseau/API.
    """
    if not token or not chat_id:
        log.warning("telegram.send.skipped_no_credentials")
        return False
    url = TELEGRAM_API_TPL.format(token=token, method="sendMessage")
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
        return True
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
