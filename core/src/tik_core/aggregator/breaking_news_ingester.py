"""Breaking-news ingester (couche 6 — alerting géopolitique / macro quasi temps réel).

But (ADR-027) : capter les **annonces non programmées** susceptibles de bouger
le BTC (Trump, géopolitique, Fed/taux, tarifs/sanctions, régulation crypto) et
envoyer une **alerte Telegram immédiate** + alimenter une carte dashboard.

C'est le chaînon manquant des alertes existantes (`notify/alerts.py`) :
- l'alerte « choc de prix » est *réactive* (se déclenche après le mouvement) ;
- l'alerte « macro imminente » ne couvre que les events *programmés* (FOMC, NFP…).
Rien ne captait une déclaration surprise (ex. accord Trump/Iran du 2026-06-14).

⚠️ Honnêteté (cohérent NO-GO + Axe #1) : c'est de l'**alerting / contexte /
discipline**, PAS un overlay directionnel. Cet ingester ne touche JAMAIS au
`combined_bias` ni à la véracité (aucun `_enrich_with_breaking_news`), donc il
ne tombe pas sous la règle « mesurer 2 sem en shadow avant enrôlement ». Et il
ne permet PAS de battre le marché : le délai réaliste est de 1-4 min après
l'événement (les pros réagissent au fil de presse en < 1 s). Valeur réelle :
te prévenir quand tu es absente/la nuit, et comprendre VITE le « pourquoi »
d'un mouvement pour ne pas trader dans la panique.

Sources (toutes gratuites, sans clé, vérifiées vivantes depuis le VPS le
2026-06-14) :
- RSS directs : BBC World, Al Jazeera, Cointelegraph
- Google News RSS, deux requêtes ciblées (macro/Trump, géopolitique)
CNBC = 403 depuis l'IP datacenter (comme Reddit), CryptoPanic exige un token,
GDELT rate-limité → écartés pour le « breaking ».

Filtre : un seul jeu de mots-clés **à fort impact** (géopol + macro + politique),
appliqué à tous les flux. Les mots crypto génériques ne déclenchent PAS (sinon
chaque article Cointelegraph alerterait) — on n'alerte que si un titre porte un
terme intrinsèquement market-moving.

Anti-spam : dédup atomique par titre normalisé (Redis SETNX + TTL 48 h), un
warm-up au 1er démarrage (on amorce le dédup sans alerter pour éviter une rafale),
filtre de fraîcheur (titre publié dans les `RECENCY_H` h), et un cap d'items par
cycle. Best-effort : aucune exception ne remonte (cohérent pattern projet).
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import json
import re
from datetime import UTC, datetime
from urllib.parse import quote_plus

import feedparser
import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester
from tik_core.config import Settings, get_settings
from tik_core.notify.telegram import send_message

log = structlog.get_logger()

USER_AGENT = "Mozilla/5.0 (compatible; TikBot/0.1)"
GOOGLE_NEWS_RSS_TPL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

# --- Paramètres (pifomètre raisonné, à calibrer post-usage) ---
INTERVAL_S = 90  # polling rapide mais doux pour des flux gratuits
RECENCY_H = 12  # on n'alerte que des titres publiés dans les 12 dernières heures
DEDUP_TTL_S = 48 * 3600  # un titre n'alerte qu'une fois sur 48 h
# Étranglement PAR CATÉGORIE : sans ça, un seul événement (ex. Trump/Iran) génère
# 40+ titres quasi identiques (mesuré 2026-06-14 : 137 titres géopol pour 1 story)
# → 40 notifications. On n'envoie donc qu'UNE alerte par catégorie / cooldown,
# avec les titres les plus frais. Le dashboard, lui, garde tout le flux.
COOLDOWN_S = 15 * 60  # 1 alerte Telegram max par catégorie / 15 min (trader veut +)
TOP_PER_CATEGORY = 4  # nb de titres montrés par catégorie dans l'alerte
RECENT_CAP = 40  # nb d'items breaking gardés pour la carte dashboard
RECENT_TTL_S = 36 * 3600

SEEN_KEY_TPL = "tik.breaking.seen:{h}"  # SETNX par titre (dédup atomique)
COOLDOWN_KEY_TPL = "tik.breaking.cd:{cat}"  # cooldown par catégorie
WARM_KEY = "tik.breaking.warm"  # flag : 1er démarrage (warm-up sans alerter)
WARM_TTL_S = 7 * 24 * 3600
RECENT_KEY = "tik.breaking.recent"  # liste JSON pour le dashboard

# --- Traduction FR des titres (best-effort via Ollama local) ---
# Les sources sont anglophones (BBC, Al Jazeera, Google News). On traduit les
# titres affichés en français. Cache par titre (Redis) pour ne pas retraduire,
# cap par cycle, fallback = titre original si échec.
# Ollama tourne sur CPU et est partagé avec les classifieurs de sentiment des
# autres ingesters → contention → ReadTimeout fréquents à 12 s (mesuré 2026-06-14 :
# 12 % de couverture seulement). Timeout 20 s + cap 4 (séquentiel) = 80 s max <
# cycle 90 s, tout en tolérant la file d'attente Ollama.
TR_CACHE_KEY_TPL = "tik.breaking.tr:{h}"
TR_CACHE_TTL_S = 7 * 24 * 3600
TR_TIMEOUT_S = 20.0
MAX_TRANSLATIONS_PER_CYCLE = 4

# --- Réaction mesurée post-alerte (feedback FACTUEL, PAS une prédiction) ---
# Après une alerte, on mesure ce que le BTC a RÉELLEMENT fait à +1 h puis +4 h
# et on l'envoie. Ce n'est pas une prédiction (Tik n'a aucun edge directionnel,
# NO-GO 2026-05-27) — c'est de l'observation factuelle pour apprendre les
# schémas réels du marché.
BTC_PRICE_KEY = "tik.last_price.BTC"
GOLD_PRICE_KEY = "tik.last_price.GOLD"  # réaction Or aussi (demande trader)
GOLD_STALE_S = 3600  # l'or a des trous (break quotidien, week-end) → seuil large
FOLLOWUP_KEY = "tik.breaking.followups"  # JSON list d'events en attente de mesure
FOLLOWUP_TTL_S = 8 * 3600
FOLLOWUP_HORIZONS_H = [1, 4]  # mesure la réaction à +1 h puis +4 h
REACTIONS_KEY = "tik.breaking.reactions"  # JSON list (réactions mesurées, dashboard)
REACTIONS_CAP = 20
REACTIONS_TTL_S = 3 * 24 * 3600

# Flux vérifiés vivants + frais depuis le VPS le 2026-06-14.
DEFAULT_FEEDS: list[dict[str, str]] = [
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
    {
        "name": "Google News",
        "url": GOOGLE_NEWS_RSS_TPL.format(
            query=quote_plus('(Trump OR "Federal Reserve" OR tariffs OR sanctions) when:1d')
        ),
    },
    {
        "name": "Google News",
        "url": GOOGLE_NEWS_RSS_TPL.format(
            query=quote_plus("(Iran OR Israel OR war OR ceasefire OR Ukraine) when:1d")
        ),
    },
    # Personnalités influentes BTC (via la presse qui rapporte leurs propos —
    # les réseaux sociaux directs ne sont pas accessibles depuis le VPS).
    {
        "name": "Google News",
        "url": GOOGLE_NEWS_RSS_TPL.format(
            query=quote_plus(
                '(Saylor OR "Elon Musk" OR "Cathie Wood" OR "Larry Fink" OR BlackRock '
                'OR MicroStrategy OR Coinbase OR "Brian Armstrong") (bitcoin OR crypto OR ETF) when:1d'
            )
        ),
    },
    # Personnalités influentes OR / macro.
    {
        "name": "Google News",
        "url": GOOGLE_NEWS_RSS_TPL.format(
            query=quote_plus(
                '("Peter Schiff" OR "Ray Dalio" OR "Warren Buffett" OR "Jamie Dimon") '
                "(gold OR bitcoin OR crypto OR Fed) when:1d"
            )
        ),
    },
    # Grands traders / investisseurs (demande trader).
    {
        "name": "Google News",
        "url": GOOGLE_NEWS_RSS_TPL.format(
            query=quote_plus(
                '("Paul Tudor Jones" OR "Stanley Druckenmiller" OR "Raoul Pal" OR '
                '"Arthur Hayes" OR "Mike Novogratz" OR "Bill Ackman" OR "Willy Woo") '
                "(bitcoin OR crypto OR gold OR markets) when:1d"
            )
        ),
    },
]

# Mots-clés À FORT IMPACT uniquement, groupés par catégorie (pour le label +
# l'emoji). Volontairement PAS de "bitcoin"/"crypto" génériques : on ne veut
# alerter que sur ce qui bouge réellement le marché. Patterns regex compilés
# insensibles à la casse ; `\b` = frontière de mot (évite les faux positifs).
KEYWORD_CATEGORIES: dict[str, list[str]] = {
    "guerre/géopol": [
        r"\bwar\b",
        r"\bwarfare\b",
        r"\bceasefire\b",
        r"\bmissile",
        r"\bairstrike",
        r"\bair strike",
        r"\binvasion\b",
        r"\binvade",
        r"\bnuclear\b",
        r"\bIran\b",
        r"\bIsrael",
        r"\bGaza\b",
        r"\bUkraine\b",
        r"\bRussia\b",
        r"\bTaiwan\b",
        r"\bHormuz\b",
        r"\bstrike on\b",
        r"\bconflict\b",
        r"\battack on\b",
        r"\bbombing\b",
        r"\bdrone strike",
    ],
    # NB : volontairement PAS de "\bTrump\b" ni "\bWhite House\b" seuls — mesuré
    # 2026-06-14 qu'ils attrapent surtout du bruit people (anniversaire, UFC,
    # Epstein…). Les vraies news Trump market-moving co-occurrent toujours avec
    # un mot-clé d'une autre catégorie (Iran, tarifs, Fed…) → captées quand même.
    "politique US": [
        r"\bexecutive order\b",
        r"\bgovernment shutdown\b",
        r"\bdebt ceiling\b",
        r"\bdebt default\b",
    ],
    "tarifs/commerce": [
        r"\btariff",
        r"\btrade war\b",
        r"\btrade deal\b",
        r"\bembargo\b",
        r"\bsanction",
    ],
    "Fed/taux/macro": [
        r"\bFederal Reserve\b",
        r"\bFed chair\b",
        r"\bcentral bank\b",
        r"\bFOMC\b",
        r"\bPowell\b",
        r"\brate cut\b",
        r"\brate hike\b",
        r"\brate decision\b",
        r"\binterest rate",
        r"\bemergency rate\b",
        r"\bjobs report\b",
        r"\brecession\b",
    ],
    "crypto/régulation": [
        r"\bSEC\b",
        r"\bstablecoin\b",
        r"\bcrypto regulation\b",
        r"\bcrypto ban\b",
        r"\bspot ETF\b",
        r"\bbitcoin ETF\b",
    ],
}

# Compilation unique (perf + lisibilité).
_COMPILED: list[tuple[str, str, re.Pattern]] = [
    (cat, pat, re.compile(pat, re.IGNORECASE))
    for cat, pats in KEYWORD_CATEGORIES.items()
    for pat in pats
]

# Personnalités influentes (BTC + or). Capté via la PRESSE qui rapporte leurs
# propos (réseaux sociaux directs non accessibles depuis le VPS). `alone_ok` :
# True = nom mono-sujet, suffit seul (Saylor ne parle que de BTC) ; False = nom
# ambigu (Musk parle de tout), exige un terme marché dans le titre (anti-bruit
# « Musk lance une fusée »). Tuple (regex, alone_ok).
INFLUENCERS: list[tuple[str, bool]] = [
    (r"\bMichael Saylor\b", True),
    (r"\bSaylor\b", True),
    (r"\bMicroStrategy\b", True),
    (r"\bPeter Schiff\b", True),
    (r"\bCathie Wood\b", True),
    (r"\bChangpeng Zhao\b", True),
    (r"\bBrian Armstrong\b", True),
    # Fink/BlackRock = géants de la finance généraliste (beaucoup de news
    # non-crypto) → exigent un contexte marché co-occurrent (anti-bruit).
    (r"\bLarry Fink\b", False),
    (r"\bBlackRock\b", False),
    (r"\bGrayscale\b", True),
    (r"\bWinklevoss\b", True),
    (r"\bTom Lee\b", True),
    (r"\bScaramucci\b", True),
    (r"\bElon Musk\b", False),
    (r"\bMusk\b", False),
    (r"\bRay Dalio\b", False),
    (r"\bWarren Buffett\b", False),
    (r"\bBuffett\b", False),
    (r"\bJamie Dimon\b", False),
    # Grands traders / investisseurs (demande trader). Crypto-natifs = seuls OK
    # (ne parlent quasi que de crypto) ; macro généralistes = exigent contexte.
    (r"\bRaoul Pal\b", True),
    (r"\bArthur Hayes\b", True),
    (r"\bMike Novogratz\b", True),
    (r"\bNovogratz\b", True),
    (r"\bWilly Woo\b", True),
    (r"\bPlanB\b", True),
    (r"\bBenjamin Cowen\b", True),
    (r"\bvan de Poppe\b", True),
    (r"\bPaul Tudor Jones\b", False),
    (r"\bStanley Druckenmiller\b", False),
    (r"\bDruckenmiller\b", False),
    (r"\bBill Ackman\b", False),
    (r"\bAckman\b", False),
    (r"\bPaul Singer\b", False),
]
_INFLUENCERS_COMPILED: list[tuple[re.Pattern, bool, str]] = [
    (re.compile(p, re.IGNORECASE), alone, p) for p, alone in INFLUENCERS
]
# Contexte marché requis pour les noms ambigus.
_MARKET_CTX = re.compile(
    r"\b(bitcoin|btc|crypto|ether|ethereum|dogecoin|doge|xrp|solana|gold|bullion|"
    r"ETF|stablecoin|halving|satoshi|MicroStrategy|Coinbase)\b",
    re.IGNORECASE,
)

_CATEGORY_EMOJI = {
    "guerre/géopol": "🌍",
    "politique US": "🏛️",
    "tarifs/commerce": "📦",
    "Fed/taux/macro": "🏦",
    "crypto/régulation": "⚖️",
    "personnalités": "🗣️",
}

# Contexte de transmission au BTC, par catégorie. RÈGLE : on explique le
# MÉCANISME dans les DEUX sens (jamais un faux "ça va monter"), cohérent
# paranoïa contrôlée (§6) + NO-GO. Affiché à chaque alerte (demande trader
# 2026-06-14). 1-2 lignes max, ↓ = baisse probable, ↑ = hausse probable.
_CATEGORY_CONTEXT = {
    "guerre/géopol": (
        "⚖️ <i>Escalade → « risk-off » : BTC souvent ↓, mais l'OR souvent ↑ (vrai refuge) "
        "→ ils divergent. Désescalade/accord → appétit pour le risque : BTC souvent ↑, "
        "OR souvent ↓. (Refuge BTC réel mais inconstant — regarde aussi le pétrole.)</i>"
    ),
    "politique US": (
        "⚖️ <i>Choc institutionnel/fiscal US → fait bouger le dollar & les taux, "
        "qui pilotent le BTC (dollar fort / taux ↑ = pression ↓ ; relance / dette = parfois ↑).</i>"
    ),
    "tarifs/commerce": (
        "⚖️ <i>Tarifs / guerre commerciale → inflation importée + « risk-off » → "
        "BTC souvent ↓ à court terme ; très sensible à la réaction du dollar.</i>"
    ),
    "Fed/taux/macro": (
        "⚖️ <i>Moteur macro n°1 : Fed « hawkish » / taux ↑ → BTC ↓ ET souvent OR ↓ "
        "(dollar fort) ; Fed « dovish » / baisse de taux → BTC ↑ et OR ↑.</i>"
    ),
    "crypto/régulation": (
        "⚖️ <i>Effet direct sur le BTC : durcissement / interdiction → ↓ ; "
        "feu vert (ETF, cadre clair) → ↑.</i>"
    ),
    "personnalités": (
        "⚖️ <i>Une figure pro-BTC (Saylor, BlackRock/Fink, Coinbase…) qui annonce un "
        "achat / un soutien = lu haussier ↑ (signal de conviction), mais l'effet est "
        "souvent déjà anticipé / court terme. Une sortie ou critique (Buffett, Schiff, "
        "Dimon, régulateur) = pression baissière ↓. Schiff/Dalio = plutôt pro-OR. "
        "À recouper avec le volume réel — pas juste la déclaration.</i>"
    ),
}


def category_context(category: str) -> str:
    return _CATEGORY_CONTEXT.get(category, "")


# ---------------- helpers purs (testables) ----------------


def normalize_title(title: str) -> str:
    """Minuscule + espaces collapsés, pour la dédup et le hash."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def dedup_hash(title: str) -> str:
    """Hash stable d'un titre normalisé (clé de dédup Redis)."""
    return hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:16]


def match_keyword(title: str) -> tuple[str, str] | None:
    """Retourne (catégorie, mot-clé matché) si le titre porte un terme à fort
    impact OU une personnalité influente, sinon None. Premier match gagne."""
    if not title:
        return None
    # 1. Catégories thématiques (géopol, Fed, tarifs, régulation…).
    for cat, pat, rx in _COMPILED:
        if rx.search(title):
            label = pat.replace(r"\b", "").replace("\\", "").strip()
            return cat, label
    # 2. Personnalités influentes : nom mono-sujet seul, ou nom ambigu +
    #    contexte marché (anti-bruit « Musk lance une fusée »).
    for rx, alone_ok, pat in _INFLUENCERS_COMPILED:
        if rx.search(title) and (alone_ok or _MARKET_CTX.search(title)):
            label = pat.replace(r"\b", "").replace("\\", "").strip()
            return "personnalités", label
    return None


def strip_gnews_suffix(title: str) -> str:
    """Retire le suffixe ' - Publisher' que Google News colle aux titres."""
    if title and " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def parse_published_iso(entry) -> str | None:
    """`entry.published_parsed` (struct_time UTC) → ISO 8601 aware UTC, ou None."""
    parsed = None
    try:
        parsed = entry.get("published_parsed") if hasattr(entry, "get") else None
    except (AttributeError, KeyError, TypeError):
        return None
    if not parsed:
        return None
    try:
        ts = calendar.timegm(parsed)
        return datetime.fromtimestamp(ts, tz=UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def is_recent(published_iso: str | None, now: datetime, recency_h: int = RECENCY_H) -> bool:
    """True si le titre est récent (ou si la date est absente — on laisse le
    dédup trancher dans ce cas)."""
    if not published_iso:
        return True
    try:
        dt = datetime.fromisoformat(published_iso)
    except ValueError:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (now - dt).total_seconds() <= recency_h * 3600


def category_emoji(category: str) -> str:
    return _CATEGORY_EMOJI.get(category, "📰")


def format_breaking_alert(groups: list[dict]) -> str:
    """Compose le message Telegram, groupé par catégorie.

    `groups` : [{"category": str, "items": [dict], "n_total": int}] — `items`
    déjà tronqué à TOP_PER_CATEGORY, `n_total` = nb total de titres frais de
    cette catégorie sur le cycle (pour le « +N autres »).
    """
    lines = ["🚨 <b>Breaking — peut bouger le BTC / l'or</b>"]
    for g in groups:
        emo = category_emoji(g["category"])
        lines.append("")
        lines.append(f"{emo} <b>{g['category']}</b>")
        for it in g["items"]:
            # title_fr (traduction) si dispo, sinon le titre original.
            title = it.get("title_fr") or it["title"]
            lines.append(f"• {title} — <i>{it['source']}</i>")
        extra = g["n_total"] - len(g["items"])
        if extra > 0:
            lines.append(f"  … <i>+{extra} autre(s)</i>")
        ctx = category_context(g["category"])
        if ctx:
            lines.append(ctx)
    lines.append("")
    lines.append(
        "ℹ️ <i>Contexte, pas signal. Vérifie ta position / ton stop. "
        "Ne trade pas dans la panique.</i>"
    )
    return "\n".join(lines)


def reaction_label(pct: float) -> str:
    """Libellé directionnel d'un mouvement de prix mesuré (pas prédit)."""
    if pct >= 0.5:
        return "🔺 hausse"
    if pct <= -0.5:
        return "🔻 baisse"
    return "➖ ~stable"


def format_reaction_alert(
    *,
    category: str,
    title: str,
    horizon_h: int,
    pct: float,
    p0: float,
    p1: float,
    gold_pct: float | None = None,
    gold0: float | None = None,
    gold1: float | None = None,
    gold_closed: bool = False,
) -> str:
    """Message de réaction mesurée BTC + Or après une alerte (factuel, non prédictif).

    L'or est affiché s'il a une mesure exploitable ; « marché fermé » s'il n'a pas
    bougé (week-end / nuit) ; omis s'il est indisponible.
    """
    emo = category_emoji(category)
    lines = [
        f"📊 <b>Réaction — {horizon_h}h après l'alerte</b>",
        f"{emo} {category} · « {title} »",
        f"₿ BTC <b>{pct:+.1f}%</b> ({p0:,.0f}$ → {p1:,.0f}$) · {reaction_label(pct)}",
    ]
    if gold_closed:
        lines.append("🥇 Or : marché fermé (pas de mesure)")
    elif gold_pct is not None and gold0 and gold1:
        lines.append(
            f"🥇 Or <b>{gold_pct:+.1f}%</b> ({gold0:,.0f}$ → {gold1:,.0f}$) "
            f"· {reaction_label(gold_pct)}"
        )
    lines.append(
        "ℹ️ <i>Mouvements réels observés, PAS une preuve de cause à effet. "
        "Pour apprendre comment le marché réagit — jamais une prédiction. "
        "(BTC et Or bougent souvent à l'opposé.)</i>"
    )
    return "\n".join(lines)


# ---------------- ingester (IO) ----------------


class BreakingNewsIngester(BaseIngester):
    """Polle des flux news rapides, filtre par mots-clés à fort impact, et
    envoie une alerte Telegram + alimente une carte dashboard. Best-effort."""

    name = "breaking_news_ingester"
    layer = 6

    def __init__(
        self,
        redis: Redis,
        *,
        settings: Settings | None = None,
        feeds: list[dict[str, str]] | None = None,
        interval_s: int = INTERVAL_S,
    ) -> None:
        self.redis = redis
        self.settings = settings or get_settings()
        self.feeds = feeds or DEFAULT_FEEDS
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "breaking_news.ingester.started",
            n_feeds=len(self.feeds),
            interval_s=self.interval_s,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("breaking_news.ingester.stopped")

    async def _fetch_feed(self, client: httpx.AsyncClient, feed: dict[str, str]) -> list[dict]:
        """Récupère et parse un flux RSS → liste de titres bruts. Best-effort."""
        try:
            r = await client.get(
                feed["url"],
                headers={"User-Agent": USER_AGENT},
                timeout=15.0,
                follow_redirects=True,
            )
            r.raise_for_status()
            content = r.text
        except Exception as exc:  # noqa: BLE001
            log.warning("breaking_news.fetch.error", feed=feed["name"], error=str(exc))
            return []
        parsed = await asyncio.to_thread(feedparser.parse, content)
        out: list[dict] = []
        for entry in list(parsed.entries or []):
            raw = entry.get("title", "") if hasattr(entry, "get") else ""
            title = strip_gnews_suffix(str(raw))
            url = entry.get("link", "") if hasattr(entry, "get") else ""
            out.append(
                {
                    "title": title,
                    "source": feed["name"],
                    "url": str(url) if url else None,
                    "published_at": parse_published_iso(entry),
                }
            )
        return out

    async def scan_once(self, *, dry_run: bool = False) -> list[dict]:
        """Un cycle : fetch tous les flux, filtre, dédup, alerte. Retourne les
        items retenus. `dry_run` : ne touche ni Redis ni Telegram (preview)."""
        now = datetime.now(tz=UTC)
        async with httpx.AsyncClient() as client:
            batches = await asyncio.gather(
                *(self._fetch_feed(client, f) for f in self.feeds)
            )
        raw_items = [it for batch in batches for it in batch]

        # Filtre mots-clés + fraîcheur.
        matched: list[dict] = []
        for it in raw_items:
            if not is_recent(it["published_at"], now):
                continue
            m = match_keyword(it["title"])
            if not m:
                continue
            category, keyword = m
            matched.append({**it, "category": category, "keyword": keyword})

        if dry_run:
            return matched

        # Dédup atomique (SETNX + TTL) : un item est "nouveau" si la clé n'existait pas.
        fresh: list[dict] = []
        for it in matched:
            seen_key = SEEN_KEY_TPL.format(h=dedup_hash(it["title"]))
            try:
                is_new = await self.redis.set(seen_key, "1", nx=True, ex=DEDUP_TTL_S)
            except Exception as exc:  # noqa: BLE001
                log.warning("breaking_news.dedup_error", error=str(exc))
                is_new = False
            if is_new:
                it = {**it, "detected_at": now.isoformat()}
                fresh.append(it)

        if not fresh:
            return []

        # Warm-up : au 1er démarrage on amorce le dédup SANS alerter (évite une
        # rafale de tout l'historique récent). Posé SEULEMENT ici (fresh non vide) —
        # sinon un 1er cycle aux flux vides "grillerait" le warm-up et le cycle
        # suivant alerterait sur tout le backlog (finding revue #4).
        warming = False
        try:
            warming = bool(await self.redis.set(WARM_KEY, "1", nx=True, ex=WARM_TTL_S))
        except Exception as exc:  # noqa: BLE001
            log.warning("breaking_news.warm_check_error", error=str(exc))

        # Traduit les titres frais en français (best-effort, cappé, caché).
        await self._translate_fresh(fresh)

        # Stocke TOUT le flux frais pour la carte dashboard (best-effort).
        await self._store_recent(fresh)

        if warming:
            log.info("breaking_news.warmup", seeded=len(fresh))
            return []  # 1er démarrage : amorcé, pas d'alerte

        # Groupe par catégorie, trie chaque groupe par fraîcheur décroissante.
        by_cat: dict[str, list[dict]] = {}
        for it in fresh:
            by_cat.setdefault(it["category"], []).append(it)
        for items in by_cat.values():
            items.sort(key=lambda x: x.get("published_at") or "", reverse=True)

        # Étranglement par catégorie : on n'alerte une catégorie que si elle
        # n'est pas en cooldown. Évite la rafale (40 variantes d'une story).
        groups: list[dict] = []
        for cat, items in by_cat.items():
            cd_key = COOLDOWN_KEY_TPL.format(cat=dedup_hash(cat))
            try:
                free = await self.redis.set(cd_key, "1", nx=True, ex=COOLDOWN_S)
            except Exception as exc:  # noqa: BLE001
                log.warning("breaking_news.cooldown_error", error=str(exc))
                free = True
            if free:
                groups.append(
                    {
                        "category": cat,
                        "items": items[:TOP_PER_CATEGORY],
                        "n_total": len(items),
                    }
                )

        if not groups:
            log.info("breaking_news.throttled", n_fresh=len(fresh))
            return fresh  # tout en cooldown : rien envoyé, mais stocké dashboard

        text = format_breaking_alert(groups)
        ok = await send_message(
            self.settings.telegram_bot_token, self.settings.telegram_chat_id, text
        )
        log.info(
            "breaking_news.alert",
            n_fresh=len(fresh),
            categories=[g["category"] for g in groups],
            sent=ok,
        )
        if ok:
            # Mesure de réaction BTC (+1 h / +4 h) sur la catégorie DOMINANTE
            # (le plus de titres), pas la 1re rencontrée (finding revue #9).
            dominant = max(groups, key=lambda g: g["n_total"])
            await self._record_followup(dominant, now)
        else:
            # Envoi échoué : on relâche les cooldowns posés pour que la prochaine
            # tentative reparte (sinon catégorie muette 45 min — finding revue #5).
            for g in groups:
                try:
                    await self.redis.delete(
                        COOLDOWN_KEY_TPL.format(cat=dedup_hash(g["category"]))
                    )
                except Exception:  # noqa: BLE001
                    pass
        return fresh

    async def _store_recent(self, items: list[dict]) -> None:
        """Pousse les items breaking dans une liste Redis cappée (dashboard)."""
        try:
            payloads = [
                json.dumps(
                    {
                        "title": it["title"],
                        "title_fr": it.get("title_fr"),
                        "source": it["source"],
                        "url": it.get("url"),
                        "category": it["category"],
                        "keyword": it.get("keyword"),
                        "published_at": it.get("published_at"),
                        "detected_at": it.get("detected_at"),
                    }
                )
                for it in items
            ]
            if payloads:
                await self.redis.lpush(RECENT_KEY, *payloads)
                await self.redis.ltrim(RECENT_KEY, 0, RECENT_CAP - 1)
                await self.redis.expire(RECENT_KEY, RECENT_TTL_S)
        except Exception as exc:  # noqa: BLE001
            log.warning("breaking_news.store_recent_error", error=str(exc))

    # ---- Traduction FR (best-effort via Ollama) ----

    async def _translate_title(self, client: httpx.AsyncClient, title: str) -> str | None:
        """Traduit un titre EN→FR via Ollama, avec cache Redis. None si échec."""
        if not title:
            return None
        key = TR_CACHE_KEY_TPL.format(h=dedup_hash(title))
        try:
            cached = await self.redis.get(key)
            if cached:
                return cached
        except Exception:  # noqa: BLE001
            pass
        prompt = (
            "Traduis ce titre de presse en français clair et journalistique. "
            "Garde les noms propres, les lieux et les chiffres exacts. Réponds "
            "UNIQUEMENT par la traduction, sans guillemets ni commentaire.\n\n" + title
        )
        try:
            r = await client.post(
                f"{self.settings.ollama_url}/api/generate",
                json={
                    "model": self.settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": "24h",
                    "options": {"temperature": 0},
                },
                timeout=TR_TIMEOUT_S,
            )
            r.raise_for_status()
            fr = (r.json().get("response") or "").strip().strip('"').strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("breaking_news.translate_error", error=str(exc) or type(exc).__name__)
            return None
        if not fr:
            return None
        try:
            await self.redis.set(key, fr, ex=TR_CACHE_TTL_S)
        except Exception:  # noqa: BLE001
            pass
        return fr

    async def _translate_fresh(self, fresh: list[dict]) -> None:
        """Ajoute `title_fr` aux titres frais (cappé, best-effort).

        Séquentiel et NON concurrent : Ollama tourne sur CPU (host VPS) et
        sérialise de toute façon — lancer 6 requêtes en parallèle faisait
        expirer les dernières (timeout). En série, chacune a son budget plein.
        """
        to_tr = fresh[:MAX_TRANSLATIONS_PER_CYCLE]
        if not to_tr:
            return
        async with httpx.AsyncClient() as client:
            for it in to_tr:
                fr = await self._translate_title(client, it["title"])
                if fr:
                    it["title_fr"] = fr

    # ---- Réaction mesurée post-alerte (factuel, pas prédictif) ----

    async def _asset_price(self, key: str, max_age_s: float = 180) -> float | None:
        """Dernier prix d'un actif (cache Redis). None si absent OU stale > max_age_s.

        Contrôle de fraîcheur (finding revue #3) : sans lui, un prix figé après un
        trou du flux fausserait silencieusement le % de réaction. Mieux vaut sauter
        la mesure (et retenter au cycle suivant) qu'un chiffre faux. L'or a un seuil
        plus large (GOLD_STALE_S) car son flux a des trous (break quotidien, week-end).
        """
        try:
            raw = await self.redis.get(key)
            if not raw:
                return None
            d = json.loads(raw)
            ts = d.get("timestamp")
            if ts:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                if (datetime.now(tz=UTC) - dt).total_seconds() > max_age_s:
                    return None  # prix périmé → mesure non fiable
            return float(d.get("price"))
        except Exception as exc:  # noqa: BLE001
            log.warning("breaking_news.price_error", key=key, error=str(exc))
        return None

    async def _record_followup(self, group: dict, now: datetime) -> None:
        """Enregistre un event à suivre (mesure de réaction BTC + Or à +1 h / +4 h)."""
        btc0 = await self._asset_price(BTC_PRICE_KEY, 180)
        if btc0 is None:
            return
        gold0 = await self._asset_price(GOLD_PRICE_KEY, GOLD_STALE_S)
        top = group["items"][0]
        title = top.get("title_fr") or top.get("title", "")
        event = {
            "category": group["category"],
            "title": title,
            "alerted_at": int(now.timestamp()),
            "btc0": btc0,
            "gold0": gold0,
            "done": [],
        }
        try:
            await self.redis.rpush(FOLLOWUP_KEY, json.dumps(event))
            await self.redis.expire(FOLLOWUP_KEY, FOLLOWUP_TTL_S)
        except Exception as exc:  # noqa: BLE001
            log.warning("breaking_news.followup_record_error", error=str(exc))

    async def _store_reaction(
        self,
        ev: dict,
        horizon_h: int,
        pct: float,
        btc1: float,
        *,
        gold_pct: float | None = None,
        gold1: float | None = None,
        gold_closed: bool = False,
    ) -> None:
        """Stocke une réaction mesurée (BTC + Or) pour la carte dashboard (best-effort)."""
        try:
            payload = json.dumps(
                {
                    "category": ev["category"],
                    "title": ev["title"],
                    "horizon_h": horizon_h,
                    "pct": round(pct, 2),
                    "btc0": ev["btc0"],
                    "btc1": btc1,
                    "gold_pct": round(gold_pct, 2) if gold_pct is not None else None,
                    "gold0": ev.get("gold0"),
                    "gold1": gold1,
                    "gold_closed": gold_closed,
                    "alerted_at": ev["alerted_at"],
                    "measured_at": int(datetime.now(tz=UTC).timestamp()),
                }
            )
            await self.redis.lpush(REACTIONS_KEY, payload)
            await self.redis.ltrim(REACTIONS_KEY, 0, REACTIONS_CAP - 1)
            await self.redis.expire(REACTIONS_KEY, REACTIONS_TTL_S)
        except Exception as exc:  # noqa: BLE001
            log.warning("breaking_news.store_reaction_error", error=str(exc))

    async def _check_followups(self) -> None:
        """Envoie les réactions mesurées dues (+1 h / +4 h) et purge les events finis."""
        try:
            raw_list = await self.redis.lrange(FOLLOWUP_KEY, 0, -1)
        except Exception as exc:  # noqa: BLE001
            log.warning("breaking_news.followup_read_error", error=str(exc))
            return
        if not raw_list:
            return
        events: list[dict] = []
        for raw in raw_list:
            try:
                events.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                continue

        now_ts = int(datetime.now(tz=UTC).timestamp())
        max_h = max(FOLLOWUP_HORIZONS_H)
        btc1: float | None = None
        gold1: float | None = None
        gold1_fetched = False
        kept: list[dict] = []
        changed = False

        for ev in events:
            done = ev.setdefault("done", [])
            for h in FOLLOWUP_HORIZONS_H:
                if h in done:
                    continue
                if now_ts - ev.get("alerted_at", now_ts) < h * 3600:
                    continue
                if btc1 is None:
                    btc1 = await self._asset_price(BTC_PRICE_KEY, 180)
                if btc1 is None or not ev.get("btc0"):
                    continue
                pct = (btc1 / ev["btc0"] - 1) * 100
                # Réaction Or (best-effort) : mesurée si l'or a bougé ; "marché
                # fermé" s'il est figé (week-end/nuit) ; omise si indisponible.
                if not gold1_fetched:
                    gold1 = await self._asset_price(GOLD_PRICE_KEY, GOLD_STALE_S)
                    gold1_fetched = True
                gold0 = ev.get("gold0")
                gold_pct: float | None = None
                gold_closed = False
                if gold0 and gold1:
                    if abs(gold1 - gold0) < 1e-9:
                        gold_closed = True
                    else:
                        gold_pct = (gold1 / gold0 - 1) * 100
                text = format_reaction_alert(
                    category=ev["category"],
                    title=ev["title"],
                    horizon_h=h,
                    pct=pct,
                    p0=ev["btc0"],
                    p1=btc1,
                    gold_pct=gold_pct,
                    gold0=gold0,
                    gold1=gold1,
                    gold_closed=gold_closed,
                )
                sent = await send_message(
                    self.settings.telegram_bot_token, self.settings.telegram_chat_id, text
                )
                log.info(
                    "breaking_news.reaction",
                    category=ev["category"],
                    horizon_h=h,
                    pct=round(pct, 2),
                    gold_pct=round(gold_pct, 2) if gold_pct is not None else None,
                    sent=sent,
                )
                done.append(h)
                await self._store_reaction(
                    ev, h, pct, btc1, gold_pct=gold_pct, gold1=gold1, gold_closed=gold_closed
                )
                changed = True
            # Garde l'event tant qu'il reste une horizon à mesurer et qu'il n'est
            # pas trop vieux (sécurité anti-fuite).
            if len(done) < len(FOLLOWUP_HORIZONS_H) and (
                now_ts - ev.get("alerted_at", now_ts)
            ) < (max_h * 3600 + 2 * 3600):
                kept.append(ev)
            else:
                changed = True

        if changed:
            # Réécriture ATOMIQUE (finding revue #1) : on construit la nouvelle
            # liste dans une clé temporaire puis `rename` (atomique côté Redis).
            # Si le process meurt avant le rename, FOLLOWUP_KEY reste intact (au
            # pire on re-mesure un event déjà fait — jamais de perte sèche, vs
            # l'ancien delete+rpush qui perdait tout en cas de crash entre les deux).
            try:
                tmp = FOLLOWUP_KEY + ".tmp"
                if kept:
                    await self.redis.delete(tmp)
                    await self.redis.rpush(tmp, *[json.dumps(e) for e in kept])
                    await self.redis.expire(tmp, FOLLOWUP_TTL_S)
                    await self.redis.rename(tmp, FOLLOWUP_KEY)
                else:
                    await self.redis.delete(FOLLOWUP_KEY)
            except Exception as exc:  # noqa: BLE001
                log.warning("breaking_news.followup_write_error", error=str(exc))

    async def _run(self) -> None:
        while self._running:
            try:
                await self.scan_once()
            except Exception as exc:  # noqa: BLE001
                log.error("breaking_news.cycle_error", error=str(exc))
            try:
                await self._check_followups()
            except Exception as exc:  # noqa: BLE001
                log.error("breaking_news.followup_cycle_error", error=str(exc))
            await asyncio.sleep(self.interval_s)


async def _preview() -> None:
    """Dry-run CLI : `python -m tik_core.aggregator.breaking_news_ingester`.

    Fetch les flux maintenant, applique le filtre, et imprime ce qui SERAIT
    alerté (sans rien envoyer ni toucher Redis). Sert à juger la couverture +
    le bruit sur les vraies news avant d'activer en prod.
    """
    ing = BreakingNewsIngester(redis=None)  # type: ignore[arg-type]
    matched = await ing.scan_once(dry_run=True)

    # Dédup par titre exact (comme le ferait Redis) pour compter les vraies stories.
    seen: set[str] = set()
    unique: list[dict] = []
    for it in matched:
        h = dedup_hash(it["title"])
        if h not in seen:
            seen.add(h)
            unique.append(it)

    by_cat: dict[str, list[dict]] = {}
    for it in unique:
        by_cat.setdefault(it["category"], []).append(it)
    for items in by_cat.values():
        items.sort(key=lambda x: x.get("published_at") or "", reverse=True)

    print(
        f"=== BREAKING (dry-run) — {len(matched)} titres bruts, "
        f"{len(unique)} après dédup titre exact ===\n"
    )
    print("Répartition par catégorie (titres uniques) :")
    for cat, items in by_cat.items():
        print(f"  {category_emoji(cat)} {cat} : {len(items)}")

    groups = [
        {"category": cat, "items": items[:TOP_PER_CATEGORY], "n_total": len(items)}
        for cat, items in by_cat.items()
    ]
    msg = format_breaking_alert(groups)
    # Nettoie les balises HTML pour la lisibilité console.
    clean = re.sub(r"<[^>]+>", "", msg)
    print("\n--- LE message Telegram que tu recevrais (1 seul, étranglé) ---")
    print(clean)


if __name__ == "__main__":
    asyncio.run(_preview())
