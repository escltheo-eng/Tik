# ADR-017 — Calendrier macro/géopolitique (Lacune B Phase B1 J+10)

**Date** : 2026-05-06
**Statut** : ACCEPTÉ
**Implémenté dans** : Paquet 10 (Phase B1 du plan trading manuel J+10)

---

## Contexte

L'utilisatrice principale de Tik prépare son passage au **trading manuel
le 2026-05-14 (J+10)**. La Phase A du plan (Top headlines, Hit rate live,
Hit rate par veracity) est livrée, mais il manquait une brique pivot
identifiée comme **Lacune B vs standard OSINT pro** au Paquet 8 (score
8/10) : le **calendrier macro/géopolitique programmé**.

Sans calendrier, on trade à l'aveugle sur les chocs macro :

- Un signal swing BTC long émis 2 h avant un FOMC peut se faire balayer
  par la décision Fed qui contre-pied le marché.
- Un signal flash GOLD short émis 30 min avant un CPI surprise voit le
  prix bouger 1-2 % en quelques minutes — bien au-dessus du stop-loss
  prévu.
- Un Initial Claims plus mauvais qu'attendu un jeudi à 8:30 ET produit
  un mouvement risk-off qui invalide les patterns techniques court terme.

L'enjeu : permettre à l'humain d'**anticiper ces fenêtres de vol violente**
et soit reporter son entrée, soit ajuster son sizing à la baisse.

Cette feature s'inscrit aussi dans la **vision long terme** documentée
en `docs/backlog.md` entry n°5 : *Tik conseiller financier macro/géopolitique*.
Le calendrier est la brique pivot — sans lui, on ne peut pas anticiper
les chocs macro.

---

## Décisions structurantes

### 1. Source : FRED Releases API (US gov officiel) + FOMC dates statiques

**Choix retenu** : combinaison de deux sources :

- **FRED Releases API** (`/fred/release/dates`) pour 7 releases majeurs
  : NFP, CPI, PPI, GDP, Retail Sales, Industrial Production, Initial
  Claims. Clé API gratuite, déjà configurée dans Tik (`fred_api_key`),
  source officielle Fed Reserve Bank of St. Louis (équivalent Bloomberg
  pour macro US).

- **Fichier statique `macro_calendar_data.FOMC_STATIC_DATES`** pour les
  meetings FOMC 2026-2027. FRED ne couvre pas proprement le statement +
  press conference (les release IDs liés sont des séries continues
  type H.15 Selected Interest Rates). Le Fed publie son calendrier 1 an
  à l'avance, donc les dates sont stables et auditables. Mise à jour
  annuelle ~30 min (1 fois/an quand le Fed publie le calendrier suivant).

**Alternatives évaluées et rejetées** :

| Source | Pour | Contre rédhibitoire |
|---|---|---|
| Scraping ForexFactory `ff_calendar_thisweek.json` | Importance native, heures précises, international | Endpoint **non officiel**, fragile (ToS ambiguë), incohérent avec pattern OSINT pro Tik (sources non citables) |
| Trading Economics API free tier | Données structurées propres, importance native | 250 req/mois free tier = 8 req/jour max, service tiers payant à terme |
| Manual JSON curé à la main | Zéro dépendance externe, contrôle total | Effort manuel récurrent permanent, infaisable pour 50+ events/mois |

Le pattern hybride **FRED API + fichier statique FOMC** offre le
meilleur compromis fiabilité × couverture × cohérence OSINT pro.

### 2. Persistance : table SQL `macro_events`

**Choix retenu** : nouvelle table `macro_events` + migration Alembic
`0005_macro_events`. Indexes sur `event_code`, `scheduled_for`,
`importance`. Contrainte UNIQUE `(event_code, scheduled_for)` pour
garantir l'idempotence des upserts.

**Alternatives évaluées** :

- **Redis only TTL 7 j** : simple, pas de migration, mais **perte
  définitive** après 7 j → pas d'audit historique possible. **Anti-pattern
  vs Lacune A déjà fixée Paquet 9** où on a justement migré vers DB
  pour l'audit. Rejeté.

- **Hybride Redis live + DB pour audit** : best of both. Mais
  complexité ajoutée pour un gain minime, vu que les events macro
  changent une fois par jour (cycle ingester FRED Calendar). Rejeté.

Volume modeste : ~50 events / mois × 10 ans = ~6000 rows. Pas
d'hypertable Timescale nécessaire. Tri DESC sur `scheduled_for` reste
performant grâce à l'index.

### 3. Périmètre Phase B1 : US-only

**Choix retenu** : **Phase B1 livre US-only** (FRED + FOMC US). 80 % de
l'impact BTC/GOLD vient des décisions Fed + données macro US (Fed pivot
+ inflation + emploi US drivent le DXY qui drive l'or et le risk-on/off
crypto).

**Phase B2 (post-J+14)** étendra à :

- ECB rate decision (BCE)
- BoJ intervention / monetary policy (Bank of Japan)
- BoE rate decision (Bank of England)
- China CPI / PMI (impact GOLD via demande safe haven asiatique)
- Élections US (mid-terms 2026, présidentielles 2028)
- Sommets G7/G20 (impact géopolitique)

Pour Phase B1, on livre **rapidement** (avant J+10) ce qui couvre 80 %
du besoin. Le reste s'enchaîne post-trading manuel selon les retours
utilisatrice.

### 4. Importance : whitelist hardcodée

**Choix retenu** : whitelist hardcodée dans `macro_calendar_data.py`,
3 niveaux `HIGH | MEDIUM | LOW` :

- **HIGH** : FOMC, NFP, CPI (déclenchent vol violente sur BTC + GOLD)
- **MEDIUM** : PPI, GDP, Retail Sales (impact réel mais plus lissé)
- **LOW** : Initial Claims, Industrial Production (data hebdo/mensuelle
  consultative, mouvements modérés sauf surprise extrême)

**Alternative évaluée — calcul dynamique post-event** : mesurer la
volatilité historique 1 h post-release sur fenêtre rolling 6-12 mois
et déduire l'importance empiriquement. Plus précis mais plus complexe
(~1 session séparée). Rejeté pour Phase B1 : la whitelist est
suffisante pour démarrer, et **calibrable post-J+30** si la mesure
empirique apporte une vraie info au-delà de la convention trader US
classique.

### 5. Lien avec les signaux Tik : zéro modification engines

**Choix retenu** : **aucune modification des engines** (`swing_engine.py`,
`flash_engine.py`, `analyze_swing_btc/gold`, `analyze_flash_btc`). Les
signaux émis ne portent **pas** de flag `macro_event_proximity`. La
relation event ↔ signal est faite **mentalement par l'humain** côté
dashboard.

**Justifications** :

- Cohérent avec le mantra *« Don't add features until users ask »* du
  2026-05-05 (engagement paranoïa contrôlée).
- Préserve **strictement** ADR-004 (multi-overlay) et la stabilité du
  pipeline scoring qui marche aujourd'hui.
- Permet une livraison **rapide** (avant J+10).
- Si l'utilisatrice demande après quelques jours de trading manuel un
  flag persisté dans le signal, ce sera **Phase B1.5 dédiée** avec ADR
  séparée (mineure) modifiant les engines.

### 6. Affichage dashboard : carte Home compact + route détail

**Choix retenu** : pattern *"Top headlines compact + bouton voir tous"*
déjà validé en Phase A.1. Carte Home (`MacroEventsCard`) avec :

- 1 ligne mise en avant pour le **next event** (countdown `dans 4 j 22 h` +
  badge importance + label + assets impactés)
- Liste compacte des 3 events suivants
- Bouton *"Voir tout le calendrier"* → route `/macro` plein écran avec
  filtres importance HIGH/MEDIUM/LOW

**Justification** : Home déjà dense (9-10 cartes empilées, cf. `docs/backlog.md`
entry n°5). Une carte full *« Calendrier macro »* aurait alourdi
l'écran. Le pattern compact + détail anticipe la refonte UX prévue
post-J+14 (tabs Marché / Calibration / Système).

---

## Implémentation

### Fichiers backend

```
core/src/tik_core/
  storage/
    models.py                     [+ MacroEvent class]
    schemas.py                    [+ MacroEventOut]
    macro_events_repo.py          [nouveau ~180 lignes]
  aggregator/
    macro_calendar_data.py        [nouveau ~270 lignes : whitelist FRED + FOMC]
    fred_calendar_ingester.py     [nouveau ~190 lignes]
  api/
    macro_events.py               [nouveau ~180 lignes]
  main.py                         [+ include_router(macro_events)]
  scripts/run_ingesters.py        [+ instance FredCalendarIngester]

core/migrations/versions/
  20260506_0000_0005_macro_events.py  [nouveau]
```

### Fichiers tests

```
core/tests/
  test_macro_calendar_data.py        [nouveau, ~14 tests]
  test_fred_calendar_ingester.py     [nouveau, ~19 tests]
  test_macro_events_repo.py          [nouveau, ~10 tests]
  test_macro_events_api.py           [nouveau, ~17 tests]
```

### Fichiers dashboard

```
dashboard/
  src/api/types.ts                          [+ type MacroEvent]
  src/api/endpoints.ts                      [+ getUpcomingMacroEvents + getMacroEventsHistory]
  src/hooks/useUpcomingMacroEvents.ts       [nouveau]
  src/utils/time.ts                         [+ timeUntil (countdown futur)]
  components/dashboard/macro-events-card.tsx [nouveau]
  app/macro/index.tsx                       [nouveau, route détail]
  app/(tabs)/index.tsx                      [+ <MacroEventsCard />]
```

### Endpoints API

- `GET /api/v1/macro_events/upcoming` — events programmés (1-720 h),
  filtre `importance`, `entity_id`. Cache Redis TTL 5 min.
- `GET /api/v1/macro_events/history` — events passés (1-365 j), audit
  ex-post. Pas de cache (utilisation rare).

Auth scope `read:signals` (réutilisé, pas de nouveau scope).

### Heures release : zoneinfo + DST automatique

Toutes les heures release sont stockées en **US/Eastern Time** (`8:30 ET`
pour BLS/BEA/Census, `9:15 ET` pour FRB Industrial Production, `14:00 ET`
pour FOMC Statement). La conversion ET → UTC est faite via
`zoneinfo.ZoneInfo("America/New_York")` qui gère automatiquement le DST :

- 8:30 ET en juin (EDT) → 12:30 UTC
- 8:30 ET en janvier (EST) → 13:30 UTC
- 14:00 ET en juillet (EDT) → 18:00 UTC
- 14:00 ET en décembre (EST) → 19:00 UTC

Tests couverts : 5 cas DST différents validés runtime via
`test_fred_calendar_ingester.py`.

---

## Conséquences

### Positives

- **Outil de risk management** indispensable pour le trading manuel J+10
  — pendant la période où Tik n'a pas démontré d'edge mesurable
  (backtest 2026-05-05 : 22 % hit BTC swing vs 33 % random sur 156
  signaux 5 j), savoir éviter les chocs macro est une discipline simple
  qui réduit le drawdown sans rien demander au scoring.
- **Convergence vers standard OSINT pro** : sources officielles
  (Bloomberg / Refinitiv / Trading Economics affichent les mêmes
  releases), citation transparente, importance documentée.
- **Pattern extensible** : pour Phase B2 (ECB, BoJ, BoE, élections),
  on étend la whitelist + on ajoute des sources statiques. Pas de
  refacto.
- **Zéro impact pipeline scoring** — engines inchangés, ADR-004
  préservée, paranoïa contrôlée maintenue.

### Négatives

- **US-only en Phase B1** — les utilisateurs européens ou asiatiques
  voudraient ECB/BoJ/BoE dès le départ. Compromis assumé pour livrer
  vite.
- **FOMC dates 2027 sont des estimations** — Fed publie habituellement
  N+1 courant septembre. À mettre à jour quand le calendrier 2027
  officiel sera publié (~2026-09-15).
- **Heures release hardcodées** — si BLS change son créneau de
  publication (rarissime), il faudra ajuster manuellement
  `macro_calendar_data.py`.
- **Pas de couplage signal↔event automatique** — l'humain fait le lien
  mentalement. Si l'utilisatrice trouve ce manque gênant après
  quelques jours, on enrichira en Phase B1.5.

### Risques opérationnels rappelés

- **Garde-fou 1** (Tik shadow vs Zeta 3 mois) **strictement applicable**
  — purement additif, zéro impact trade automatique.
- **Garde-fou 2-bis** (sizing 1 % au démarrage trading manuel — cf.
  CLAUDE.md section 5) **rappelé fortement** : la carte calendrier
  aide à éviter les chocs macro mais ne **garantit** pas la performance.
- **ADR-003** (pas de bypass V01-V15) **inchangé**.
- **ADR-004** (multi-overlay) **inchangé** — Phase B1 ne touche pas
  le pipeline scoring.
- **Pattern OSINT pro respecté** — FRED = source officielle citée,
  dates précises, transparence importance via whitelist documentée.

---

## Validation runtime requise au déploiement

1. **Vérifier les release_ids FRED** : depuis le Mac, avec la vraie clé
   FRED de production :
   ```
   curl "https://api.stlouisfed.org/fred/releases?api_key=$FRED_API_KEY&file_type=json&limit=200"
   ```
   Comparer avec les `release_id` de `FRED_RELEASES` dans
   `macro_calendar_data.py`. Si un ID est faux, le ingester loggera
   un warning mais l'event sera skip — pas de crash.

2. **Vérifier les FOMC dates 2027** : consulter
   `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm`
   et corriger les estimations si le Fed a publié son calendrier 2027.

3. **Cycle ingester complet** : observer dans les logs après restart
   `docker compose restart ingesters` :
   ```
   fred_calendar.ingester.started n_fred_releases=7 n_static_events=12 interval_s=86400
   fred_calendar.cycle_complete n_events_built=N n_upserted=M
   ```
   Si `n_upserted=0` alors que `n_events_built > 0`, vérifier les
   logs warning `macro_events_repo.upsert_error`.

4. **Endpoint réponse** :
   ```
   curl -H "Authorization: Bearer $TIK_KEY" \
     "http://localhost:8200/api/v1/macro_events/upcoming?limit=5"
   ```
   Doit retourner une liste JSON triée ASC par `scheduled_for`, avec
   suffix `Z` sur les datetimes (cohérent ADR-013).

5. **Carte Home iPhone** : ouvrir l'app via Expo Go, vérifier la
   présence de la carte *« Calendrier macro »* sous *« Top headlines »*,
   avec un countdown lisible (*« FOMC dans X j Y h »*).

---

## Mise à jour annuelle

**Quand le Fed publie son calendrier FOMC N+1** (généralement courant
septembre) :

1. Ajouter les nouvelles dates dans `FOMC_STATIC_DATES` en respectant
   l'ordre chronologique (test `test_fomc_static_dates_chronological_order`
   le verrouille).
2. Bumper la version core / dashboard si livré séparément.
3. Documenter dans CLAUDE.md (section 8 ou changelog).

Pour Phase B2 (international), prévoir aussi un module ECB/BoJ/BoE
calendar — soit nouveau ingester, soit extension de
`macro_calendar_data.py` avec des nouvelles structures `EcbStaticDates`,
etc.

---

## Liens

- CLAUDE.md section 5 — Garde-fous opérationnels (Garde-fou 2-bis ajouté
  pour le sizing 1 % au démarrage trading manuel)
- CLAUDE.md section 8 — Couches non-implémentées : Phase B2 internationalisation
- `docs/backlog.md` entry n°3 — Plan trading manuel J+10
- `docs/backlog.md` entry n°5 — Vision Tik conseiller financier macro
- ADR-003 — Pas de bypass V01-V15 (inchangé)
- ADR-004 — Multi-overlay architecture (inchangée)
- ADR-013 — Timezone-aware datetimes (sérialisation `iso_utc` réutilisée)
