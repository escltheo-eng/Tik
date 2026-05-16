# ADR-020 — Calendrier macro multi-banques centrales (Phase B2)

**Date** : 2026-05-16
**Statut** : ACCEPTÉ
**Implémenté dans** : Paquet 23 (P9 du plan stratégique fiabilité signaux post-Paquet 18)

---

## Contexte

ADR-017 (Phase B1, livré le 2026-05-06) a posé le **calendrier macro US**
dans Tik : FOMC + 7 release FRED (NFP, CPI, PPI, GDP, Retail Sales,
Industrial Production, Initial Claims). Discipline opérationnelle pour la
trader manuelle J+14 : ne pas entrer en swing dans les ±4 h autour d'un
event HIGH (cf. Garde-fou 2-bis dans CLAUDE.md section 5).

**Limite identifiée en Phase B1** (et inscrite dans le backlog #5 vision
long terme + le plan stratégique post-audit fiabilité signaux P9) :

> US-only. Phase B2 post-J+14 pour ECB/BoJ/BoE/élections (sources : ECB
> calendar JSON, BoJ static, BoE static, agrégateur élections à choisir).

Or les banques centrales internationales bougent aussi violemment les
actifs trade par Tik :

- **ECB Governing Council** (Lagarde) : mouvements EUR/USD ±1-2 %, transmission
  DXY → BTC + GOLD.
- **BoJ Monetary Policy Meeting** (Ueda) : la BoJ a cassé pendant 30 ans
  le yield curve control. Une normalisation surprise = sell-off carry
  trade, mouvement BTC violent par déleveraging mondial.
- **BoE MPC Bank Rate Decision** (Bailey) : moindre mais réel sur GBP →
  DXY → BTC/GOLD via transmission de second ordre.

Sans calendrier international, la trader manuelle est aveugle aux 24
events majeurs internationaux par an (3 BC × 8 meetings) qui peuvent
expliquer un mouvement BTC/GOLD apparemment "techniques" mais en
réalité macro.

**Bug latent découvert lors de l'audit Phase B1** : le
`FredCalendarIngester` skip si `api_key=""` — donc sans clé FRED
configurée, les FOMC dates statiques ne sont **pas non plus** upsertées
en DB (alors qu'elles ne dépendent pourtant pas de FRED). C'est l'occasion
de séparer proprement les responsabilités.

---

## Décisions structurantes

### 1. Architecture : nouvel ingester `MacroStaticIngester` séparé

**Choix retenu** : créer `core/src/tik_core/aggregator/macro_static_ingester.py`
qui gère **exclusivement** les dates statiques (FOMC + ECB + BoJ + BoE).
Le `FredCalendarIngester` est élagué — il ne gère plus que les 7 release
FRED dynamiques.

**Pour** :
- **Fix bug latent** : sans clé FRED, MacroStaticIngester continue de
  pousser FOMC + ECB + BoJ + BoE. Discipline préservée.
- **Séparation des responsabilités** : un ingester par type de source
  (dynamic vs static).
- **Zéro dépendance externe** pour MacroStaticIngester (pas de fetch HTTP,
  pas de clé API). Robustesse maximale.
- **Symétrie** : symétrique du pattern Phase B1 qui avait FRED dynamique
  + FOMC static mélangés.

**Contre** :
- +1 ingester dans la liste boot. Marginal (~30 lignes de code, 1 tâche
  asyncio supplémentaire).

**Alternatives rejetées** :
- Étendre `FredCalendarIngester` pour aussi pousser ECB/BoJ/BoE. Garde le
  bug latent et donne un nom mensonger ("FredCalendar" pour ECB).

### 2. Sources des dates : hardcodées en Python (pattern FOMC Phase B1)

**Choix retenu** : dates ECB / BoJ / BoE hardcodées dans
`macro_calendar_data.py`, alimentées depuis les sites officiels :

- ECB : https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html
- BoJ : https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm
- BoE : https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates

**Pour** :
- **Auditabilité** : la liste est dans un fichier versionné Git, review
  PR-able, type-checkable.
- **Cohérence** avec FOMC Phase B1 (même approche).
- **Pas de scraping HTML fragile** ni de dépendance à un endpoint API
  externe versionable.
- **Mise à jour annuelle ~30 min** quand chaque BC publie son calendrier
  N+1 (généralement courant septembre N-1 pour ECB/BoE, fin N-1 pour BoJ).

**Contre** :
- Si une date est reportée d'urgence (rare : pandémie, crise), il faut
  faire une PR. Acceptable car les BC sont très disciplinées sur leurs
  calendriers annoncés.

**Alternatives rejetées** :
- Scraper ECB JSON officiel (existe mais format instable, qualité du
  parsing dépend du calendrier annoncé) — bénéfice incertain vs coût.
- API agrégée payante (TradingEconomics, Investing.com) — payante, hors
  scope MVP gratuit.

### 3. Timezones : `tz_name` IANA sur `StaticEventSpec` + `FredReleaseSpec`

**Choix retenu** : ajouter un champ `tz_name: str` (default
`"America/New_York"` pour rétrocompat Phase B1) à `StaticEventSpec` et
`FredReleaseSpec`. La fonction `date_to_utc_release(iso_date, hour,
minute, tz_name="America/New_York")` prend ce paramètre pour gérer
correctement le DST de chaque fuseau (`Europe/Paris` CEST/CET,
`Asia/Tokyo` JST sans DST, `Europe/London` GMT/BST,
`America/New_York` EST/EDT).

**Pour** :
- **Une seule structure de données** pour FOMC US + ECB EU + BoJ JP +
  BoE UK. Pas de classe par BC.
- **Rétrocompat Phase B1** : default `America/New_York` → tests Phase B1
  inchangés.
- **DST géré automatiquement** par `zoneinfo` stdlib Python 3.9+.

**Contre** :
- Le nom de champ `release_hour_et` (= Eastern Time) devient légèrement
  mensonger pour ECB Frankfurt / BoJ Tokyo / BoE London. Pas renommé en
  `release_hour_local` pour éviter une cascade de migrations sur les
  tests Phase B1. Dette de naming acceptée, documentée en commentaire.

### 4. Champ `source` sur `StaticEventSpec`

**Choix retenu** : ajouter `source: str` au `StaticEventSpec` (default
`"fed_static"` rétrocompat Phase B1). Valeurs : `"fed_static"`,
`"ecb_static"`, `"boj_static"`, `"boe_static"`.

**Pour** :
- Permet de filtrer côté API si l'utilisatrice veut juste les events ECB
  ou juste BoJ (extension `entity_id`/`importance` actuelle de
  `/macro_events/upcoming`).
- Trace d'audit : on sait quelle BC a publié l'event.

**Contre** :
- Plus de strings à maintenir cohérentes (pas un vrai problème vu le
  petit nombre).

**Alternatives rejetées** :
- Une enum stricte → coût refactor sans bénéfice immédiat.

### 5. Importance par BC : FOMC HIGH, ECB HIGH, BoJ HIGH, BoE MEDIUM

**Choix retenu** :

| BC | Importance | Justification |
|---|---|---|
| FOMC (Fed) | HIGH | Mouvement BTC/GOLD le plus brutal — DXY pivot mondial. |
| ECB | HIGH | EUR/USD = 2e paire FX, transmission DXY → BTC/GOLD violente. |
| BoJ | HIGH | Carry trade JPY casse → sell-off risk-on mondial, BTC inclus. |
| BoE | MEDIUM | GBP moins influente sur DXY que EUR/USD, impact modulé. |

**Contre** :
- Calibration au pifomètre raisonné. À recalibrer empiriquement
  post-J+30 sur observations réelles de la vol BTC/GOLD autour de
  chaque event (cf. backlog #7 calibrations en attente).

### 6. Pas d'élections en Phase B2 (reportées Phase B3)

**Choix retenu** : couvrir ECB + BoJ + BoE uniquement en Phase B2.
Les élections majeures (US midterms, présidentielles, allemandes,
britanniques, japonaises, françaises) sont reportées à Phase B3.

**Pour** :
- **Focus** : 3 BC = pattern uniforme, sources officielles transparentes,
  mise à jour 1 fois/an.
- **Scope élections** = lourd : 50+ élections mondiales par an, source
  agrégée à choisir (IFES, ACE Project, NDI), critères de pertinence
  trading à définir (G7 only ? G20 ? émergents critiques ?).
- **Risque faux sentiment de discipline** : couverture incomplète des
  élections donnerait l'illusion d'une "discipline électorale" mais
  manquerait des events majeurs.

**Quand attaquer Phase B3** : post-J+30 selon retour utilisatrice. Si la
discipline calendrier macro Phase B1+B2 est confirmée utile en pratique,
attaquer les élections G7 (~30 events/4 ans) en mode statique
hardcodé (même pattern que FOMC).

---

## Implémentation

### Fichiers modifiés

| Fichier | Changement |
|---|---|
| `core/src/tik_core/aggregator/macro_calendar_data.py` | Ajout `tz_name` sur specs, `source` sur StaticEventSpec, helpers `date_to_utc_release`/`build_event_from_*` déplacés ici, +3 listes `ECB_STATIC_DATES`/`BOJ_STATIC_DATES`/`BOE_STATIC_DATES` (12 dates 2026-2027 chacune), helper `all_static_events()`. |
| `core/src/tik_core/aggregator/fred_calendar_ingester.py` | Retrait FOMC static du cycle. Devient FRED-only. Réexport rétrocompat des helpers déplacés. |
| `core/src/tik_core/aggregator/macro_static_ingester.py` | **Nouveau**. `MacroStaticIngester` qui upsert all_static_events() à chaque cycle daily. Pas de clé API requise. |
| `core/src/tik_core/scripts/run_ingesters.py` | Ajoute `MacroStaticIngester(session_maker=..., interval_s=24*3600)` dans la liste boot. |
| `core/tests/test_macro_calendar_data.py` | +43 tests : invariants structurels ECB/BoJ/BoE, helper `date_to_utc_release` avec 4 timezones, `all_static_events()`, `build_event_from_static` avec 4 sources. |
| `core/tests/test_fred_calendar_ingester.py` | Refactor 1 test : `test_ingester_cycle_includes_static_fomc` (Phase B1) → `test_ingester_cycle_does_not_include_static_fomc` (Phase B2 négatif) + nouveau `test_ingester_cycle_includes_fred_dates_only`. |
| `core/tests/test_macro_static_ingester.py` | **Nouveau**. 10 tests : lifecycle (no session_maker → skip), `_cycle()` upsert all_static_events, counts par source, best-effort sur erreur DB, structure events. |
| `docs/adr/020-multi-central-banks-static-ingester.md` | Ce fichier. |
| `docs/comprendre_tik.md` | Section pédagogique "Calendrier macro multi-banques centrales". |
| `docs/backlog.md` | Entry #5 mise à jour : Phase B2 ✅ livrée. |

### Schéma DB et API : aucune modification

La table `macro_events` (Phase B1, migration `0005_macro_events`) est
déjà domain-agnostic :
- `source: str` accepte n'importe quelle valeur → `"ecb_static"`,
  `"boj_static"`, `"boe_static"` viennent s'ajouter à `"fred"` et
  `"fed_static"`.
- `assets_impacted: JSON` accepte `["BTC", "GOLD"]` pour toutes les BC.

Le schéma Pydantic `MacroEventOut` et les endpoints
`GET /api/v1/macro_events/{upcoming,history}` n'ont pas changé. La carte
Home dashboard `MacroEventsCard` (Phase B1) affichera ECB Lagarde / BoJ
Ueda / BoE Bailey automatiquement, **sans aucune modification frontend**.

C'est exactement l'effet visé par la conception domain-agnostic Phase B1
(`ADR-017` décisions 4 et 5) : l'extension a un coût marginal.

---

## Risques opérationnels rappelés

- **Garde-fou 1** (Tik shadow vs Zeta 3 mois) **inchangé**. Tik ne crée
  jamais d'ordre, ni avant ni après cette livraison.
- **ADR-003** (pas de bypass V01-V15) **inchangé**. Aucun nouveau canal
  d'exécution.
- **ADR-004** (multi-overlay) **inchangé**. Le calendrier macro reste un
  outil de discipline pour l'humain, **pas un input des engines**. Les
  signaux Tik continuent d'être dérivés strictement du `combined_bias`
  OSINT (post-ADR-018) sans modulation par les events macro.
- **Garde-fou 2-bis** (sizing 1 %, veracity ≥ 0.90, discipline macro ±4 h
  autour d'un event HIGH) **renforcé empiriquement** : la discipline
  s'étend maintenant aux events ECB/BoJ/BoE en plus de FOMC/NFP/CPI.

---

## Limites connues post-livraison

1. **Dates 2026-2027 ECB/BoJ/BoE = effort raisonné, pas garanties**.
   Basées sur les patterns publiés. À vérifier par l'utilisatrice via
   les sites officiels avant déploiement runtime. L'UNIQUE constraint
   `(event_code, scheduled_for)` protège contre les doublons mais pas
   contre une date erronée → événement manqué. Correction : éditer
   `macro_calendar_data.py` + restart ingesters (idempotent).

2. **2027 = estimations sur patterns**. Les BC publient généralement N+1
   courant septembre N-1 → calendrier 2027 confirmé sera publié mi-2026.
   Mise à jour annuelle dans `macro_calendar_data.py`.

3. **Heures release hardcodées** : 14:00 ET FOMC, 14:15 CET ECB,
   12:00 JST BoJ, 12:00 GMT/BST BoE. Si une BC déplace son créneau de
   release (rare mais arrive — BoJ a déjà bougé sur le statement 2x dans
   les 10 dernières années), il faut éditer la liste.

4. **Pas de couplage automatique signal ↔ event proche**. L'humain fait
   le lien mentalement (« je vois ECB dans 3 h, je n'entre pas »). Une
   Phase B2.5 envisageable selon retour usage : poser un flag
   `near_macro_event` sur les signaux émis dans la fenêtre ±4 h. Mais
   reporté car risque d'over-engineering avant retour terrain réel.

5. **Importance BoE MEDIUM = calibration au pifomètre**. À recalibrer
   empiriquement post-J+30 sur observations vol BTC/GOLD autour des
   meetings BoE (cf. backlog #7 calibrations en attente, ajout d'une
   entrée B.4 pour ce point).

6. **Pas de signaux différenciés par direction du change** : on flag
   l'event mais pas s'il s'agit d'une hausse ou baisse de taux attendue.
   La trader manuelle doit faire ce raisonnement elle-même (lire les
   minutes BC + consensus marché). Ajout futur potentiel : champ
   `expected_decision` (rate up/cut/hold) avec source (Reuters/Bloomberg
   consensus) — hors scope Phase B2.

---

## Référence à des paquets et ADR connexes

- ADR-017 (Phase B1, FOMC + FRED US) — pattern source
- ADR-018 (Tik pure OSINT) — Tik n'influence pas les engines via
  calendrier macro, c'est juste un outil pour l'humain
- Paquet 11 (livraison Phase B1, 2026-05-06)
- Paquet 18 (refactor OSINT pur, 2026-05-07)
- backlog #5 (vision long terme conseiller financier macro) — Phase B2
  marque la première extension internationale
- backlog #7 (calibrations en attente) — recalibration importance BoE
  + heures release à valider runtime
