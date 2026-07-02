"""Tests des helpers purs du breaking-news ingester (ADR-027).

Couvre le filtre mots-clés (précision/recall, dont l'anti-bruit "Trump seul"),
la dédup par titre, la fraîcheur, le parsing de date et le formatage groupé.
Sans réseau ni DB.

Ajout audit 2026-07-02 (T3) : tests du cycle `scan_once` (warm-up en mémoire
process — bug « clé Redis warm expirée = cycle d'alertes avalé » — et intervalle
configurable par env TIK_BREAKING_NEWS_INTERVAL_S), avec un FakeRedis en mémoire
et Telegram mocké.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from tik_core.aggregator.breaking_news_ingester import (
    KEYWORD_CATEGORIES,
    WARM_KEY,
    BreakingNewsIngester,
    _env_interval_s,
    category_context,
    category_emoji,
    dedup_hash,
    format_breaking_alert,
    format_reaction_alert,
    is_recent,
    match_keyword,
    normalize_title,
    parse_published_iso,
    reaction_label,
    strip_gnews_suffix,
)
from tik_core.config import Settings

# ---------- normalize_title / dedup_hash ----------


def test_normalize_collapses_and_lowercases():
    assert normalize_title("  Trump   says\nIRAN  deal ") == "trump says iran deal"


def test_dedup_hash_stable_and_case_insensitive():
    assert dedup_hash("Deal reached with Iran") == dedup_hash("deal   reached with iran")


def test_dedup_hash_differs_on_different_titles():
    assert dedup_hash("Iran deal reached") != dedup_hash("Fed cuts rates")


# ---------- match_keyword : recall (vrais positifs) ----------


def test_match_geopolitics_iran():
    cat, _ = match_keyword("Deal reached between the United States and Iran, Trump says")
    assert cat == "guerre/géopol"


def test_match_geopolitics_war():
    cat, _ = match_keyword("Trump says Iran and US have reached deal to stop war")
    assert cat == "guerre/géopol"


def test_match_tariffs():
    cat, _ = match_keyword("Trump's tariffs hit small businesses")
    assert cat == "tarifs/commerce"


def test_match_fed():
    cat, _ = match_keyword("The Kevin Warsh Era Begins at the Federal Reserve")
    assert cat == "Fed/taux/macro"


def test_match_rate_cut():
    cat, _ = match_keyword("Fed signals a rate cut at next meeting")
    assert cat == "Fed/taux/macro"


def test_match_executive_order():
    cat, _ = match_keyword("President signs executive order on digital assets")
    assert cat == "politique US"


def test_match_crypto_regulation():
    cat, _ = match_keyword("SEC approves new spot ETF rules")
    assert cat == "crypto/régulation"


# ---------- match_keyword : précision (vrais négatifs / anti-bruit) ----------


def test_no_match_trump_gossip():
    # "Trump" seul ne doit PAS matcher (anti-bruit people, mesuré 2026-06-14).
    assert match_keyword("Trump celebrates his 80th birthday at a UFC cage fight") is None


def test_no_match_generic_crypto():
    # Un mouvement de prix crypto générique ne doit pas alerter.
    assert match_keyword("Bitcoin rises 2% as traders eye weekend") is None


def test_no_match_sports():
    assert match_keyword("Japan deny Netherlands at the World Cup opener") is None


def test_no_match_empty():
    assert match_keyword("") is None


# ---------- match_keyword : personnalités influentes ----------


def test_match_influencer_saylor_alone():
    # Saylor = mono-sujet BTC → suffit seul.
    cat, _ = match_keyword("Michael Saylor hints at another Bitcoin purchase")
    assert cat == "personnalités"


def test_match_influencer_musk_with_market_context():
    # Musk = ambigu → matche seulement avec un terme marché (ici Dogecoin).
    cat, _ = match_keyword("Elon Musk tweets about Dogecoin again")
    assert cat == "personnalités"


def test_no_match_musk_without_market_context():
    # Musk sans contexte marché = bruit (fusée) → ne matche pas.
    assert match_keyword("Elon Musk's SpaceX launches a new rocket") is None


def test_match_influencer_schiff_gold():
    cat, _ = match_keyword("Peter Schiff says gold will outperform stocks")
    assert cat == "personnalités"


def test_personnalites_has_bidirectional_context():
    ctx = category_context("personnalités")
    assert ctx
    assert "↓" in ctx and "↑" in ctx


# ---------- strip_gnews_suffix ----------


def test_strip_gnews_suffix():
    assert strip_gnews_suffix("Deal reached with Iran - Reuters") == "Deal reached with Iran"


def test_strip_gnews_suffix_no_suffix():
    assert strip_gnews_suffix("Deal reached with Iran") == "Deal reached with Iran"


# ---------- is_recent ----------


def test_is_recent_true():
    now = datetime(2026, 6, 14, 22, 0, tzinfo=UTC)
    iso = (now - timedelta(hours=2)).isoformat()
    assert is_recent(iso, now) is True


def test_is_recent_false_when_old():
    now = datetime(2026, 6, 14, 22, 0, tzinfo=UTC)
    iso = (now - timedelta(hours=20)).isoformat()
    assert is_recent(iso, now) is False


def test_is_recent_true_when_no_date():
    # Date absente → on laisse le dédup trancher (ne pas jeter l'item).
    now = datetime(2026, 6, 14, 22, 0, tzinfo=UTC)
    assert is_recent(None, now) is True


# ---------- parse_published_iso ----------


def test_parse_published_iso_ok():
    entry = {"published_parsed": time.struct_time((2026, 6, 14, 21, 48, 0, 0, 0, 0))}
    out = parse_published_iso(entry)
    assert out is not None
    assert out.startswith("2026-06-14T21:48")


def test_parse_published_iso_missing():
    assert parse_published_iso({}) is None


# ---------- category_emoji ----------


def test_category_emoji_known():
    assert category_emoji("guerre/géopol") == "🌍"


def test_category_emoji_fallback():
    assert category_emoji("inconnu") == "📰"


# ---------- format_breaking_alert ----------


def test_format_groups_and_extra():
    groups = [
        {
            "category": "guerre/géopol",
            "items": [
                {"title": "US and Iran reach deal", "source": "Google News"},
                {"title": "Hormuz to reopen", "source": "Al Jazeera"},
            ],
            "n_total": 50,
        }
    ]
    msg = format_breaking_alert(groups)
    assert "Breaking" in msg
    assert "US and Iran reach deal" in msg
    assert "+48 autre(s)" in msg  # 50 - 2 montrés
    assert "Contexte, pas signal" in msg
    # Le contexte de mécanisme doit apparaître (demande trader 2026-06-14).
    assert "risk-off" in msg


# ---------- category_context ----------


def test_every_category_has_context():
    # Toute catégorie de mots-clés doit avoir un contexte de mécanisme associé,
    # avec au moins une direction explicite (↓ ou ↑).
    for cat in KEYWORD_CATEGORIES:
        ctx = category_context(cat)
        assert ctx, f"contexte manquant pour {cat}"
        assert "↓" in ctx or "↑" in ctx


def test_geopolitics_and_fed_context_bidirectional():
    # Là où les deux sens sont réels (ex. trader 2026-06-14), on explique ↓ ET ↑.
    for cat in ("guerre/géopol", "Fed/taux/macro"):
        ctx = category_context(cat)
        assert "↓" in ctx and "↑" in ctx, f"{cat} doit être bidirectionnel"


def test_category_context_unknown_empty():
    assert category_context("inconnu") == ""


# ---------- title_fr (traduction affichée) ----------


def test_format_alert_prefers_title_fr():
    groups = [
        {
            "category": "guerre/géopol",
            "items": [
                {
                    "title": "US and Iran reach deal",
                    "title_fr": "Les États-Unis et l'Iran concluent un accord",
                    "source": "Google News",
                }
            ],
            "n_total": 1,
        }
    ]
    msg = format_breaking_alert(groups)
    assert "Les États-Unis et l'Iran concluent un accord" in msg
    assert "US and Iran reach deal" not in msg  # le FR remplace l'EN


def test_format_alert_falls_back_to_original_title():
    groups = [
        {
            "category": "Fed/taux/macro",
            "items": [{"title": "Fed cuts rates", "source": "BBC World"}],
            "n_total": 1,
        }
    ]
    msg = format_breaking_alert(groups)
    assert "Fed cuts rates" in msg  # pas de title_fr → titre original


# ---------- réaction mesurée ----------


def test_reaction_label_directions():
    assert "hausse" in reaction_label(1.2)
    assert "baisse" in reaction_label(-1.2)
    assert "stable" in reaction_label(0.1)


def test_format_reaction_alert_factuel():
    msg = format_reaction_alert(
        category="guerre/géopol",
        title="Accord US-Iran",
        horizon_h=1,
        pct=-2.3,
        p0=65000.0,
        p1=63505.0,
    )
    assert "1h après" in msg
    assert "-2.3%" in msg
    assert "baisse" in msg
    # Honnêteté : explicitement PAS une prédiction / pas de causalité prouvée.
    assert "PAS une preuve de cause" in msg
    assert "jamais" in msg and "prédiction" in msg


# ---------- réaction BTC + Or ----------


def test_format_reaction_with_gold():
    msg = format_reaction_alert(
        category="Fed/taux/macro",
        title="Baisse de taux",
        horizon_h=1,
        pct=1.5,
        p0=65000.0,
        p1=65975.0,
        gold_pct=-0.8,
        gold0=2400.0,
        gold1=2380.8,
    )
    assert "BTC" in msg and "+1.5%" in msg
    assert "Or" in msg and "-0.8%" in msg


def test_format_reaction_gold_closed():
    msg = format_reaction_alert(
        category="guerre/géopol",
        title="x",
        horizon_h=4,
        pct=2.0,
        p0=100.0,
        p1=102.0,
        gold_closed=True,
    )
    assert "marché fermé" in msg


def test_format_reaction_gold_omitted_when_unavailable():
    msg = format_reaction_alert(
        category="guerre/géopol", title="x", horizon_h=1, pct=1.0, p0=100.0, p1=101.0
    )
    assert "🥇" not in msg  # pas de ligne Or si indisponible


# ---------- nouveaux grands traders ----------


def test_match_trader_arthur_hayes():
    cat, _ = match_keyword("Arthur Hayes predicts a Bitcoin rally")
    assert cat == "personnalités"


def test_match_trader_tudor_jones_with_context():
    cat, _ = match_keyword("Paul Tudor Jones boosts gold and bitcoin allocation")
    assert cat == "personnalités"


def test_no_match_tudor_jones_without_context():
    assert match_keyword("Paul Tudor Jones attends a charity gala") is None


def test_blackrock_now_requires_market_context():
    # BlackRock seul (finance générique) ne matche plus (anti-bruit).
    assert match_keyword("BlackRock acquires a real estate firm") is None
    # Avec contexte marché → matche.
    cat, _ = match_keyword("BlackRock CEO turns bullish on crypto markets")
    assert cat == "personnalités"


# =============================================================================
# Warm-up (audit 2026-07-02) — flag mémoire process, clé Redis = garde restart
# =============================================================================


class FakeRedis:
    """Mock Redis en mémoire, minimal pour `scan_once` (SET NX/EX + listes)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def set(self, key, value, nx=False, ex=None):  # noqa: ARG002
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, *keys) -> None:
        for key in keys:
            self.store.pop(key, None)
            self.lists.pop(key, None)

    async def lpush(self, key, *values) -> None:
        self.lists.setdefault(key, [])[:0] = list(reversed(values))

    async def rpush(self, key, *values) -> None:
        self.lists.setdefault(key, []).extend(values)

    async def ltrim(self, key, start, stop) -> None:
        if key in self.lists:
            self.lists[key] = self.lists[key][start : stop + 1]

    async def expire(self, key, ttl) -> bool:  # noqa: ARG002
        return True

    async def lrange(self, key, start, stop):
        values = self.lists.get(key, [])
        return values[start:] if stop == -1 else values[start : stop + 1]

    async def rename(self, src, dst) -> None:
        if src in self.lists:
            self.lists[dst] = self.lists.pop(src)


def _settings() -> Settings:
    return Settings(telegram_bot_token="token-test", telegram_chat_id="chat-test")


def _item(title: str) -> dict:
    return {"title": title, "source": "BBC World", "url": None, "published_at": None}


def _make_scan_ingester(redis: FakeRedis, monkeypatch) -> tuple[BreakingNewsIngester, list[str]]:
    """Ingester prêt pour `scan_once` : 1 flux factice, Telegram + traduction mockés."""
    ing = BreakingNewsIngester(
        redis,  # type: ignore[arg-type]
        settings=_settings(),
        feeds=[{"name": "BBC World", "url": "http://fake.local/rss"}],
        interval_s=300,
    )
    sent: list[str] = []

    async def fake_send(_token, _chat_id, text, **_kwargs) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr("tik_core.aggregator.breaking_news_ingester.send_message", fake_send)

    async def noop_translate(_fresh) -> None:
        return None

    ing._translate_fresh = noop_translate
    return ing, sent


def _set_feed(ing: BreakingNewsIngester, items: list[dict]) -> None:
    """Court-circuite le fetch réseau : le flux retourne `items` tels quels."""

    async def fake_fetch(_client, _feed) -> list[dict]:
        return items

    ing._fetch_feed = fake_fetch


async def test_warmup_first_cycle_seeds_without_alerting(monkeypatch):
    """1er démarrage (clé Redis absente) : le 1er cycle utile amorce la dédup
    sans alerter ; un titre déjà vu n'alerte plus, un nouveau titre alerte."""
    redis = FakeRedis()
    ing, sent = _make_scan_ingester(redis, monkeypatch)

    _set_feed(ing, [_item("Iran ceasefire collapses after strikes")])
    out = await ing.scan_once()
    assert out == []  # warm-up : amorcé, pas d'alerte
    assert sent == []
    assert WARM_KEY in redis.store  # garde anti-restart posée

    # Même titre au cycle suivant → dédup 48h, rien de neuf, pas d'alerte.
    fresh = await ing.scan_once()
    assert fresh == []
    assert sent == []

    # Nouveau titre → alerte envoyée (le warm-up ne mange qu'UN cycle).
    _set_feed(ing, [_item("Fed announces emergency rate decision")])
    fresh = await ing.scan_once()
    assert len(fresh) == 1
    assert len(sent) == 1


async def test_warmup_not_rearmed_when_redis_key_expires_on_hot_process(monkeypatch):
    """Reproduction du bug audit 2026-07-02 : process « chaud » (déjà warmé) +
    clé Redis warm EXPIRÉE (TTL 7 j) → les alertes doivent quand même partir.

    Avant le fix, `scan_once` re-consultait SET NX à chaque cycle : la clé
    expirée re-déclenchait un warm-up → la fournée d'items était consommée par
    la dédup 48 h SANS alerte Telegram (cycle d'alertes avalé en silence)."""
    redis = FakeRedis()
    ing, sent = _make_scan_ingester(redis, monkeypatch)

    # Cycle 1 : vrai 1er démarrage → warm-up normal.
    _set_feed(ing, [_item("Iran ceasefire collapses after strikes")])
    assert await ing.scan_once() == []
    assert sent == []

    # Simule l'expiration de la clé Redis warm (7 j) sur un process qui tourne.
    await redis.delete(WARM_KEY)
    assert WARM_KEY not in redis.store

    # Cycle N : nouveau breaking → l'alerte DOIT partir (flag mémoire process).
    _set_feed(ing, [_item("Fed announces emergency rate decision")])
    fresh = await ing.scan_once()
    assert len(fresh) == 1
    assert len(sent) == 1, "cycle d'alertes avalé : le warm-up s'est réarmé à tort"


async def test_warmup_skipped_on_restart_when_redis_key_still_present(monkeypatch):
    """Restart rapide (clé Redis warm encore vivante) : pas de re-warm-up —
    la dédup 48 h est déjà amorcée, les alertes partent dès le 1er cycle."""
    redis = FakeRedis()
    redis.store[WARM_KEY] = "1"  # posée par le run précédent, non expirée
    ing, sent = _make_scan_ingester(redis, monkeypatch)  # instance neuve = restart

    _set_feed(ing, [_item("Fed announces emergency rate decision")])
    fresh = await ing.scan_once()
    assert len(fresh) == 1
    assert len(sent) == 1


async def test_warmup_not_consumed_by_empty_cycles(monkeypatch):
    """Finding revue #4 préservé : un 1er cycle sans item frais ne grille pas
    le warm-up (sinon le cycle suivant alerterait sur tout le backlog)."""
    redis = FakeRedis()
    ing, sent = _make_scan_ingester(redis, monkeypatch)

    _set_feed(ing, [])  # flux vides au boot
    assert await ing.scan_once() == []
    assert WARM_KEY not in redis.store  # warm-up pas consommé
    assert ing._first_cycle_done is False

    # 1er cycle UTILE → warm-up, pas d'alerte.
    _set_feed(ing, [_item("Iran ceasefire collapses after strikes")])
    assert await ing.scan_once() == []
    assert sent == []
    assert ing._first_cycle_done is True


# =============================================================================
# Intervalle configurable TIK_BREAKING_NEWS_INTERVAL_S (audit 2026-07-02)
# =============================================================================


def test_env_interval_default_is_300(monkeypatch):
    monkeypatch.delenv("TIK_BREAKING_NEWS_INTERVAL_S", raising=False)
    assert _env_interval_s() == 300


def test_env_interval_override(monkeypatch):
    monkeypatch.setenv("TIK_BREAKING_NEWS_INTERVAL_S", "120")
    assert _env_interval_s() == 120


def test_env_interval_floor_60s(monkeypatch):
    # Borne basse anti-matraquage : jamais sous 60 s même si l'env le demande.
    monkeypatch.setenv("TIK_BREAKING_NEWS_INTERVAL_S", "5")
    assert _env_interval_s() == 60


def test_env_interval_invalid_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("TIK_BREAKING_NEWS_INTERVAL_S", "abc")
    assert _env_interval_s() == 300


def test_ingester_interval_from_env_and_explicit(monkeypatch):
    monkeypatch.setenv("TIK_BREAKING_NEWS_INTERVAL_S", "600")
    ing = BreakingNewsIngester(FakeRedis(), settings=_settings())  # type: ignore[arg-type]
    assert ing.interval_s == 600
    # Un interval_s explicite garde la priorité sur l'env.
    explicit = BreakingNewsIngester(
        FakeRedis(),  # type: ignore[arg-type]
        settings=_settings(),
        interval_s=90,
    )
    assert explicit.interval_s == 90
