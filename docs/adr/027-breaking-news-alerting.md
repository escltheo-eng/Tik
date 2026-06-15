# ADR-027 — Breaking-news alerting (géopolitique / macro quasi temps réel)

**Date** : 2026-06-14
**Statut** : ACCEPTÉ (alerting, gaté par toggle `TIK_BREAKING_NEWS_ENABLED`, défaut OFF)
**Implémenté dans** : `core/src/tik_core/aggregator/breaking_news_ingester.py`
**Déclencheur** : perte trader sur le BTC suite à l'annonce non programmée « accord
Trump/Iran » du 2026-06-14 au soir (chute du pétrole −5 %, contagion crypto).

---

## Contexte

Tik avait **deux** alertes Telegram (`notify/alerts.py`, job toutes les 15 min) :

1. **Choc de prix BTC** — ≥ 3 % sur 6 h. *Réactive* : se déclenche **après** le mouvement.
2. **Macro imminente** — event HIGH **programmé** (FOMC, NFP, CPI) ≤ 60 min avant.

**Le trou** : une annonce **non programmée** (déclaration Trump, accord géopolitique,
décision surprise de banque centrale) n'était captée par **rien**. Le seul ingester
news BTC interroge Google News avec le mot « Bitcoin » uniquement — pas « Trump »,
« Iran », « Fed », « guerre ». La géopolitique pure n'était suivie nulle part côté BTC
(GDELT = GOLD uniquement, requête « gold price »). C'est exactement l'angle mort qui a
coûté de l'argent à la trader le 2026-06-14.

## Décision

Ajouter un **ingester breaking-news** qui polle des flux rapides, filtre par mots-clés
à fort impact, et envoie une **alerte Telegram immédiate** + alimente une **carte
dashboard**. Gaté par `TIK_BREAKING_NEWS_ENABLED` (défaut OFF, activé après validation).

### Périmètre honnête (cohérent NO-GO + Axe #1)

C'est de l'**ALERTING / contexte / discipline**, **PAS un overlay directionnel** :
- aucun `_enrich_with_breaking_news`, **zéro ligne touchée dans les moteurs** ;
- ne touche **jamais** le `combined_bias` ni la véracité ;
- ne tombe donc **pas** sous la règle « mesurer 2 sem en shadow avant enrôlement »
  (cette règle protège le `combined_bias` ; ici on n'y touche pas) ;
- ne change **rien** au go/no-go directionnel du 2026-05-27.

**Limite assumée — ça ne bat PAS le marché.** Délai réaliste de bout en bout 1-4 min
après l'événement (flux gratuit polled à 90 s + envoi Telegram). Les pros réagissent
au fil de presse en < 1 s. Valeur réelle : (a) prévenir la trader **quand elle est
absente / la nuit** pour gérer son risque (sortir, réduire, vérifier son stop) ; (b)
comprendre **vite le « pourquoi »** d'un mouvement pour ne pas trader dans la panique.
La vraie protection contre « perdre sur une annonce du soir » reste le **sizing 1 % +
ne pas tenir de levier BTC dans une fenêtre de risque + stop** (Garde-fou 2-bis) — le
flux est un complément, pas le remède.

### Sources (gratuites, sans clé — vérifiées vivantes depuis le VPS le 2026-06-14)

| Source | URL | Verdict |
|---|---|---|
| **BBC World** | `feeds.bbci.co.uk/news/world/rss.xml` | ✅ 200, frais |
| **Al Jazeera** | `aljazeera.com/xml/rss/all.xml` | ✅ 200, très frais |
| **Cointelegraph** | `cointelegraph.com/rss` | ✅ 200, frais |
| **Google News** (2 requêtes ciblées macro + géopol) | `news.google.com/rss/search?q=...` | ✅ 200 (pattern déjà utilisé) |
| CNBC | `cnbc.com/.../rss.html` | ❌ 403 (IP datacenter bloquée, comme Reddit) |
| CryptoPanic | `cryptopanic.com/api/v1/posts` | ❌ exige un token gratuit |
| GDELT | `api.gdeltproject.org/.../doc` | ⚠️ rate-limité (1 req / 5 s) |

### Filtre + anti-bruit (mesuré, pas spéculé — engagement #10)

Un dry-run sur les vraies news du 2026-06-14 a **capté l'événement** (« Deal reached
between the United States and Iran, Trump says », « crude oil falls ~5% … Strait of
Hormuz », et l'**anticipation** « Trump Says Iran Deal Is Imminent ») — mais a révélé
**198 titres** retenus dont **137 en géopol**, presque tous **la même story** répétée
par 40 médias. Deux garde-fous en réponse :

1. **Étranglement par catégorie** (`COOLDOWN_S = 45 min`) : une catégorie n'alerte
   qu'une fois par fenêtre, avec ses 3 titres les plus frais (`+N autres`). Un seul
   message Telegram lisible au lieu de 40 notifications.
2. **Précision du filtre** : un seul jeu de mots-clés **à fort impact** (géopol +
   macro + politique fiscale + tarifs + régulation crypto), **sans** « Trump » /
   « White House » seuls — mesuré qu'ils n'attrapent que du bruit people
   (anniversaire, UFC, Epstein). Les vraies news Trump market-moving co-occurrent
   toujours avec un autre mot-clé (Iran, tarifs, Fed) → captées quand même. Pas de
   mot crypto générique (« bitcoin »/« crypto ») pour ne pas alerter sur chaque
   article de prix.

Autres garde-fous : dédup atomique par titre (Redis `SETNX` + TTL 48 h), **warm-up**
au 1er démarrage (amorce le dédup sans alerter → pas de rafale d'historique), filtre
de fraîcheur (titre publié ≤ 12 h). Best-effort intégral (aucune exception ne remonte).

## Alternatives écartées

- **Source payante temps réel** (Reuters/Bloomberg wire) — § 7 « pas de budget API »,
  et 2 000 €+/mois injustifiable au stade NO-GO.
- **Brancher GDELT sur le breaking** — rate-limité + batches 15 min, pas « breaking ».
- **Garder « Trump » comme mot-clé seul** — bruit people majoritaire (mesuré).
- **Émettre un overlay directionnel depuis les news** — violerait NO-GO + Axe #1 +
  ADR-018 (la direction vient du `combined_bias`, pas d'une réaction à chaud).

## Conséquences

- **+** Comble le seul angle mort des alertes (annonces non programmées).
- **+** Réversible / sans risque : toggle OFF par défaut, zéro impact moteur, retrait =
  retirer la ligne dans `run_ingesters.py`.
- **−** Délai de minutes (pas de secondes) — ne bat pas le marché (assumé).
- **−** Filtre par mots-clés → angles morts possibles (formulation inattendue) + un
  reste de bruit géopolitique en période de crise (atténué par le cooldown).
- **−** Fiabilité des flux gratuits non garantie (plusieurs sources en parallèle pour
  amortir).

## Amendement 2026-06-14 (v2) — FR + réaction mesurée (demande trader)

Suite à la demande de la trader (« en français » + « dis-moi si c'est haussier/baissier ») :

1. **Traduction FR des titres** (best-effort via Ollama local, cache Redis
   `tik.breaking.tr:{h}`, cap 6/cycle, fallback = titre original). Telegram + carte
   dashboard affichent `title_fr` si dispo. Qualité « machine » (~85 %) assumée, la
   source reste visible/cliquable. Choix : **traduction** (pas synthèse LLM) pour
   éviter l'hallucination (cohérent philosophie « titres bruts » top-headlines).

2. **Réaction MESURÉE post-alerte** (réponse honnête à « haussier/baissier ») : on
   ne **prédit pas** (NO-GO, aucun edge directionnel) ; on **mesure** ce que le BTC a
   réellement fait à **+1 h** et **+4 h** après chaque alerte et on l'envoie (Telegram
   + carte « Réactions mesurées »). Mécanisme : `tik.breaking.followups` (events à
   suivre, btc0 capté via `tik.last_price.BTC`) → `_check_followups()` chaque cycle →
   message factuel avec disclaimer « mouvement réel observé, PAS une preuve de cause à
   effet, jamais une prédiction ». Stocké dans `tik.breaking.reactions` (endpoint
   `GET /metrics/breaking_reactions`). **But** : bâtir au fil des semaines un vrai jeu
   de **base rates par catégorie** (la seule route honnête vers « ce qui arrive
   d'habitude »).

Tests : 31 verts (`test_breaking_news_ingester.py`). Honnêteté Axe #1 préservée :
toujours zéro overlay directionnel, la réaction est rétrospective et explicitement
non-prédictive.

## Amendement 2026-06-14 (v3) — personnalités influentes (BTC + or)

Demande trader : « ajouter les annonces des personnes les plus influentes sur le BTC
et l'or… réseaux sociaux ou autre ». **Limite assumée et dite** : les flux sociaux
directs (X/Twitter, Truth Social) ne sont **pas** accessibles gratuitement/fiablement
depuis le VPS (API payante 100 $+/mois ; scraping bloqué sur IP datacenter, comme
Reddit Bug 11). On capte donc leurs propos **via la presse qui les rapporte** (délai
de quelques minutes, comme le reste du breaking).

- **2 requêtes Google News dédiées** ajoutées (figures BTC : Saylor, Musk, Fink/
  BlackRock, Cathie Wood, Coinbase, MicroStrategy ; figures or/macro : Schiff, Dalio,
  Buffett, Dimon) — 7 flux au total.
- **Catégorie « personnalités »** avec matching à deux niveaux (`INFLUENCERS`) : noms
  mono-sujet (Saylor, Schiff…) acceptés seuls ; noms ambigus (Musk, Buffett…) exigent
  un terme marché co-occurrent (`_MARKET_CTX`) → anti-bruit « Musk lance une fusée ».
- **Contexte bidirectionnel** dédié (pro-BTC qui achète → ↑ souvent déjà anticipé ;
  critique/sortie → ↓ ; Schiff/Dalio pro-or).
- **Angle OR** ajouté aux contextes existants (géopol : BTC ↓ / OR ↑ divergent ; Fed),
  header « peut bouger le BTC / l'or ». 36 tests verts.

**Réponse au « donne tes prédictions »** : refus assumé d'une prédiction directionnelle
(même habillée) — on fournit à la place QUI/QUOI + lecture bidirectionnelle (les 2
scénarios + pourquoi) + réaction mesurée + (futur) base rates. La seule « prédiction »
honnête = des probabilités rétrospectives mesurées, jamais une intuition.

## Amendement 2026-06-15 (v4) — + d'alertes, réaction BTC+Or, grands traders

Demandes trader : (1) **plus d'alertes** → `COOLDOWN_S` 45 → **15 min**/catégorie,
`TOP_PER_CATEGORY` 3 → 4. (2) **Réaction mesurée BTC ET Or** côte à côte (l'or bouge
souvent à l'opposé) : `_record_followup` capte aussi `gold0` (`tik.last_price.GOLD`,
seuil de fraîcheur large `GOLD_STALE_S=1h`), `_check_followups` calcule `gold_pct`,
gère « marché fermé » (or figé `gold0==gold1`, week-end/nuit) et « indisponible »
(or absent → ligne omise). Schéma `BreakingReaction` + endpoint + carte étendus
(gold_pct/gold0/gold1/gold_closed). (3) **Grands traders** ajoutés aux personnalités
(Tudor Jones, Druckenmiller, Raoul Pal, Arthur Hayes, Novogratz, Ackman, PlanB,
Willy Woo…) + 8ᵉ flux Google News dédié.

Audit qualité de cette livraison (sous consigne « paranoïa, zéro erreur ») : revue
adversariale indépendante (11 findings → 10 corrigés dont 3 majeurs : race
`delete+rpush`→rename atomique, fraîcheur prix, warm-up robuste ; 5 acceptés
documentés). Vérifs : **1557+ tests** verts, ruff/eslint/tsc 0, endpoints HTTP+auth
prouvés, runtime live OK, réaction BTC+Or testée (−1,96 %/+1,01 %). Détail mémoire
`breaking-news-alerting-adr027`.

## Suites

- **Base rates par catégorie** (après ~2-3 semaines de réactions) : carte « réaction
  BTC typique par type d'event » (moyenne ± dispersion, % baissier) — version honnête
  et mesurée de « haussier/baissier », rétrospective.
- Alerte « fenêtre de risque » quand plusieurs events HIGH se cumulent (discipline).
- Lier les events breaking au **Carnet** (trade journal) : trades passés près d'une news.
- Calibrer `COOLDOWN_S` / mots-clés / qualité de traduction à l'usage.
- Option : CryptoPanic (token gratuit) ou flux FR natifs (France24) si besoin.
