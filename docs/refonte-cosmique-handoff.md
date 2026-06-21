# Passation — Refonte UX « cosmique » + audit veracity (2026-06-15)

> **Pour la prochaine instance Claude** : ce document = l'état exact où on en est.
> Lis-le en entier, puis lis `CLAUDE.md` (contexte projet) et la mémoire
> `layout-ux-overhaul-deferred`. Tout le travail UI vit sur la branche
> **`refonte-cosmique`** (main intact = 100 % réversible).

---

# ⭐ ÉTAT ACTUEL (2026-06-19) — LIRE EN PREMIER

> La refonte UX cosmique est **structurellement complète ET polie** (tous les écrans
> sont cosmiques, plus aucun écran « thémé »). Tout est sur la branche
> **`refonte-cosmique`**, poussé sur `origin`, **commits `9a6bc9f` → `fe2b9d3`**.
> `main` = ancien design intact (réversible : `git checkout main`, ou révoquer un commit isolé).
> Les sections plus bas (« Décisions actées », bouts 1→6, audit veracity) sont l'**historique**.
>
> **Dernière session 2026-06-19 (validée trader)** — cf. la sous-section « 🗓 Session 2026-06-19 »
> plus bas pour le détail + les bugs trouvés/corrigés (A13/A14/A15 + jauge sweep).

## Pourquoi cette refonte (le « pourquoi » à ne pas perdre)
Le problème de départ n'était PAS la couleur mais l'**ergonomie** : signal de trading enterré en
position #13 sur la Home, 14 cartes empilées sans hiérarchie. La trader a recadré en cours de route
(« c'est juste le même layout en cosmique ? ») → on est passé du **reskin** à une vraie **refonte
par tâche**. Cible : plateforme OSINT trading manuel, **pro + débutant**, **bot-ready** (place
réservée), **jolie ET ergonomique**. Garde-fou transverse **Axe #1** : Tik n'a **aucun edge
directionnel prouvé** (NO-GO 2026-05-27) → l'UI aide à décider avec **discipline/contexte**, JAMAIS
faire passer conviction/accord pour des gages de fiabilité.

## Navigation = 5 onglets cosmiques (`app/(tabs)/_layout.tsx`)
| Onglet | Fichier | Rôle |
|---|---|---|
| **Cockpit** | `app/(tabs)/index.tsx` | « Puis-je trader ? » : bandeau macro réel (liquidité/récession/taux) + **statut discipline F1** (4 critères ✓/⚠, « freins » ≠ achat) + **derniers signaux BTC + GOLD côte-à-côte** (tuiles compactes `SignalTile`, tap → détail) + **Breaking enrichi** (âge + réactions BTC/Or mesurées + mécanisme ↓/↑ par catégorie) + **Dernières actus** (bull/bear + dates + « voir toutes » → page dédiée) + trades ouverts + prochain event |
| **Signals** | `app/(tabs)/signals.tsx` | Liste filtrable (Tous/BTC/GOLD · Flash/Swing/Macro · 24h/5j/30j) + **pastilles stabilité dépliables au tap** (BTC = carnet d'ordres + flux agressif + accord ; GOLD = stabilité swing, pas de microstructure flash) + statut Live. En-tête « Tik · signals » (safe-area corrigée). Tap ligne → détail cosmique |
| **Sources** | `app/(tabs)/sources.tsx` | **Constellation** santé sources + **Polymarket** (barres proba + échéance + **volume/marché + volume total + fraîcheur**) + **dérivés** (bras de fer long/short) |
| **Carnet** | `app/(tabs)/journal.tsx` | Journal de trades manuels (snapshot Tik à l'entrée) |
| **Plus** | `app/(tabs)/plus.tsx` | Profil « Lola & Théo » + **hero hit-rate** + grille perf + **jauge hit-rate vs baseline** (demi-cercle SVG — sweep corrigé 2026-06-19) + **hit-rate par accord** (ex-« par veracity », cosmique) + **stats LLM** (cosmique) + **hub** (Watchlist · Calendar · Alerts · Config · About · Bots placeholder, badge alertes non-lues) |

**Masqués de la barre** (`href:null`, atteints via le hub Plus) : `watchlist`, `alerts`, `config`, `bots`, `about`.
**Routes hors-onglets** (Stack racine `app/_layout.tsx`, header sombre) : `signal-cosmique/[id]` (détail cosmique), `macro-cosmique` (page Régime/Liquidité/Taux Fed), `macro/index` (**calendrier cosmique** gamma 03), `headlines/[entityId]` (**page « Dernières actus » cosmique**, cap 25 + dates + pull-to-refresh — atteinte via « Voir toutes les actus » du Cockpit). ⚠ L'ancien `signal/[id].tsx` (thémé) est **conservé mais orphelin** (plus rien ne le route — supprimable au besoin).

## Design system cosmique (`constants/cosmic.ts`)
- Palette `Cosmic` : fond `#0a0c14`/`#06070d`, carte `#141a2b`, **texte crème `#e8e4dc`** (chaud, doux OLED), accent ambre `#ffc15e`, long `#6ec5a2` / short `#e87a7a` / neutral `#e8b86b` / macro `#7d9ed3`.
- `TitleShadow.strong/.soft/.glow` (reliefs ; `glow` = halo ambré des gros titres), `serifTitleFamily` (serif système = New York iOS, en attendant les vraies polices).
- **Thème sombre FORCÉ global** : `hooks/use-color-scheme.ts` + `.web.ts` renvoient `'dark'`, et `Colors.dark` (`constants/theme.ts`) est reteinté cosmique → les rares écrans encore « thémés » (login, cartes veracity-buckets/LLM) rendent sombre. ⚠ `tint` gardé **bleu** (boutons à texte blanc en dur → blanc-sur-ambre illisible).

## Composants cosmiques (`components/cosmic/`)
`cosmic-background` (fond étoilé SVG) · `cosmic-signal-card` (carte signal, prop `variant: summary|detail`) · `cosmic-signal-row` (ligne liste) · `cosmic-news` (**CosmicHeadlines** bull/bear + dates + `onSeeAll` ; **CosmicBreaking** catégories + âge + **réactions BTC/Or** + **mécanisme par catégorie**) · `cosmic-source-health` (**constellation**) · `cosmic-derivatives` (**bras de fer**) · `cosmic-polymarket` (**barres proba + échéance + volume**) · `cosmic-hit-rate` (**jauge demi-cercle SVG** vs baseline) · `cosmic-collapsible` (section dépliable cosmique partagée, évite le rectangle sombre du `Collapsible` thémé dans une carte) · `cosmic-macro-regime-card` / `cosmic-global-liquidity-card` / `cosmic-rate-probabilities-card` (cartes macro de `/macro-cosmique`).
**Données 100 % réelles** (hooks existants réutilisés, zéro backend touché). **BTC + GOLD only.**

## EXCLU (ne pas réintroduire sans données / sans demande) — Axe #1
**Silver** (entité inexistante), **index Stress** (donnée inexistante), **« influence » orbitale chiffrée** (contredit ADR-004 = moyenne NON pondérée → ce serait du vernis inventé). « veracity » est nommé **« accord »** dans l'UI.

## 🗓 Session 2026-06-19 (validée trader, commits `c941ae7` → `fe2b9d3`)

Deux temps : (A) finir le polish des écrans secondaires, (B) répondre à une liste de
demandes trader + corriger des bugs trouvés en passant.

**(A) Polish écrans secondaires (`c941ae7`)** — les 4 derniers écrans « thémés » du hub Plus
passent au cosmique complet : **Alerts**, **Config** (formulaire/push/switch/glossaire ;
boutons ambre **texte sombre** = lisible, pas de blanc-sur-ambre), **About** (abandon du
parallax daté), **Bots** (placeholder). + les 2 cartes thémées de Plus (hit-rate par accord +
stats LLM). Extraction du composant partagé **`cosmic-collapsible`** (le `Collapsible` thémé
peignait un rectangle `#0a0c14` dans une carte `#141a2b`). « veracity » → « accord » (A9).

**(B) Demandes trader + bugs (`020302d` + `fe2b9d3`)** :
- **Cockpit** : dernier signal BTC **+ GOLD côte-à-côte** en tuiles compactes (`SignalTile`),
  tap → détail. *Choix layout : 2 cartes riches côte-à-côte ne tiennent pas en largeur tél →
  tuiles ; le « pourquoi » riche reste à 1 tap. Validé trader.*
- **Breaking enrichi** : port fidèle de l'ex-`breaking-news-card.tsx` (orpheline) → âge
  (`source · il y a X`), **réactions mesurées BTC + Or**, **mécanisme ↓/↑ par catégorie**.
  Bug **A14** : `breaking.reactions` était produit par `useBreakingNews` mais **jamais passé**
  au composant cosmique → corrigé.
- **Signals — détail stabilité au tap** : les pastilles « court terme BTC/GOLD » se **déplient**
  (avant = `Alert`). BTC = carnet d'ordres + flux agressif + accord (via
  `computeFlashStability().cross`). ⚠ **GOLD n'a PAS de carnet/flux** (pas de moteur flash,
  Yahoo +15 min) — donc équivalent honnête = stabilité **swing** (la demande « GOLD avec
  carnet/flux comme avant » reposait sur une prémisse fausse : l'ancienne carte était BTC-only).
- **Dernières actus** : **date par ligne** + bouton « Voir toutes les actus » qui **navigue**
  vers `/headlines/[entity]` (route cosmétisée). Avant = expand inline.
- **Polymarket** : bug **A15** = `question` en `numberOfLines={1}` (tronquée) → 2 lignes ;
  ajout **volume/marché + volume total + fraîcheur** du snapshot.
- **Titre « Tik · signals » coupé** : bug **A13** = `signals.tsx` était le **seul** écran cosmique
  sans `insets.top` → titre sous l'encoche. Ajout safe-area.
- **Jauge hit-rate « mal affichée »** (`fe2b9d3`) : le demi-cercle SVG avait **sweep-flag 0**
  depuis sa création (`058c77e`) → arc dessiné **par le bas** (milieu y=156, hors viewBox 92,
  coupé) + remplissage sur un **autre cercle** + repère baseline déconnecté. **Fix = sweep
  0→1** (vérifié par la paramétrisation centre de la spec SVG : track milieu y=12 = haut,
  remplissage recentré sur (100,84)). **Validé trader.**

**Anomalies trackées** : A13 (safe-area Signals), A14 (`breaking.reactions` non câblé),
A15 (Polymarket question tronquée), + jauge sweep-flag. Toutes corrigées.

**Non fait délibérément** : aucun claim marché ajouté par recherche web (texte mécanisme =
**validé existant** réutilisé ; cf. mémoire `macro-reading-removed-2026-05-30` — des claims
WebSearch précédents étaient faux 2/4 → vernis Axe #1).

**Non vérifié** : rendu pixel sur device (je valide tsc/eslint/bundle, pas le pixel — la trader
a confirmé visuellement GOLD tiles, Breaking, stabilité, Polymarket, titre Signals, et la jauge).

## 🗓 Session 2026-06-19 (soir) — Page Macro : horloge de séances + discipline + mesure macro

Demande trader : « un onglet de signaux émis **grâce au macro** » + « **triangulation**
Europe/Asie/US pour trader au **bon moment de la plage horaire** » (BTC + GOLD).

**Reframe honnête (Axe #1 / ADR-028)** : des « signaux macro » directionnels = **INTERDIT**
(le macro est `context_only`, ne touche jamais la direction) **et** jamais mesuré → refusé.
La vraie intention (« bons moments de plage horaire ») = faisable comme **CONTEXTE/DISCIPLINE**.

**Livré sur la page Macro** (`/macro-cosmique`, accès via le bandeau Signals/Cockpit — **PAS un
onglet** : un onglet a été testé puis **abandonné**, choix trader « garder 5 onglets ») :
- **Horloge de séances** — `components/cosmic/cosmic-session-clock.tsx` + logique **pure**
  `src/macro/sessions.ts` : Sydney/Tokyo/Londres/NY ouvert/fermé selon l'heure d'été (règles
  UE/US/AU calculées, **sans `Intl`**), chevauchement Londres–NY, « creux quotidien » NY→Sydney,
  or COMEX (pause quotidienne + jours fériés via `US_MARKET_HOLIDAYS`). **36 assertions** prouvées
  par exécution. Commit `f91dea5`.
- **Fenêtres de discipline** — `cosmic-discipline-window.tsx` + `src/macro/discipline.ts` :
  prochains events HIGH (FOMC/NFP/CPI/BCE/BoJ) + alerte **±4 h** (Garde-fou 2-bis). **14 assertions**.
  Commit `46f5c9a`.
- **Triangulation Europe/Asie/US = DÉJÀ couverte** par la carte *Liquidité mondiale* (Fed/ECB/BoJ
  côte à côte, barre de composition) → **aucun « Bout C » construit** (aurait été redondant). Le
  régime PROPRE de chaque région exigerait un ajout backend (gaté « pas d'ajout sans manque mesuré »).

**Chantier mesure (« les deux ») — `core/src/tik_core/scripts/measure_macro_predictive.py`**
(lecture seule) : teste si la liquidité (net + mondiale) et les taux réels **précèdent** BTC/GOLD
(IC Spearman, fenêtres non chevauchantes, vs Always SHORT). **Résultat 2026-06-19 = AUCUN edge
macro prédictif** : les IC non-nuls sont de la **colinéarité de niveau** / du **mauvais signe**
(taux réel→BTC +0.43 non-chev mais hypothèse inverse) / des **artefacts du régime haussier**
2023-26. La variation Δ4 sem (le vrai signal) ≈ 0 ; GOLD ~0 partout. **Confirme ADR-028** (macro =
contexte) **+ NO-GO**. Re-mesurer après un changement de régime. Mémoire
`macro-predictive-measurement-2026-06-19`.

**Décisions trader (2026-06-19, RÉSOLUES)** : (1) **Europe 16:00 UTC** = on garde le standard été
(Londres locale 17:00 BST, ne pas l'élargir) ; (2) **rendu pixel** de la page Macro **validé**.

**Vérifs** : tsc + eslint + bundle iOS verts ; **50 assertions** de logique pure (sessions 36 +
discipline 14) prouvées ; script macro tourné + **ruff (config repo) « All checks passed »**.

## 🗓 Session 2026-06-20 — Jauges macro + rafraîchissement auto au premier plan

- **Jauges macro** (cf. « Reste à faire » #3 ci-dessous, marqué FAIT) : commit `76495b0`.
- **Rafraîchissement auto sans reload** (demande trader « je ne veux pas avoir besoin de
  toujours recharger ») : nouveau hook partagé `src/hooks/use-app-foreground.ts` qui appelle
  un callback au retour au premier plan (AppState non-active → active). Branché sur **`useTick`**
  (horloge de séances + tous les « il y a X min » se rafraîchissent à la reprise) et sur **les 12
  hooks de données** (`useMacroRegime`, `useRateProbabilities`, `useDerivatives`, `usePolymarket`,
  `useTopHeadlines`, `useUpcomingMacroEvents`, `useHitRate`, `useHitRateByVeracity`,
  `useDashboardKpis` via `refresh` ; `useSourceHealth`, `useBreakingNews`, `useSignalFreshness`
  via un listener AppState inline car leur `run` n'est pas exposé). `useSignalStream` gérait DÉJÀ
  le retour au premier plan (rien à changer). **Cause racine** : l'OS gèle `setInterval` en
  arrière-plan → au retour il fallait attendre le prochain tick (jusqu'à 15 min pour la macro).
  ⚠ Pour tout NOUVEAU hook de poll : penser à `useAppForeground(refresh)`. Mémoire
  `dashboard-foreground-refresh`.
- **« Toutes séances fermées » = PAS un bug** : c'était le week-end (samedi). La carte affiche
  bien le bandeau « 🌙 Week-end — forex & or fermés (BTC 24/7) ». Code `sessions.ts` juste.

## 🗓 Session 2026-06-20 (soir) — Observatoire : vue orbitale honnête des sources (commit `e092eb8`)

Reprise du « reste à faire » #5 (vue orbitale). Les 2 maquettes orbitales ont été **lues**
pour la 1re fois : elles affichent des **« % d'influence »** par source + des sources que Tik
**n'a pas** (Whales/CoinGlass payant, ETF Gold, Silver, satellites DXY/US10Y/CPI séparés). La
trader a explicitement validé une **version honnête** (le « % d'influence » serait un chiffre
**inventé** : la veracity est une moyenne **non pondérée** ADR-004 → aucune source ne pèse plus
qu'une autre).

**Livré — page dédiée `/observatoire`** (atteinte via un bouton « ✦ Vue orbitale » en haut de
l'onglet **Sources** ; PAS un onglet — vue de contexte « prendre du recul ») :
- **Un soleil central = l'actif** (bascule **BTC / GOLD**) + sa **direction** et son **accord**
  (= veracity) du dernier signal **swing**.
- **Sources en orbite** = les vrais overlays OSINT de l'actif. Couleur = **santé** (🟢 vivante /
  🟠 en retard / 🔴 muette / ⚫ désactivée). Tap → panneau détail : **texte verbatim** de la source
  (`evidence[].fact`, ex. « FG=23 (Extreme Fear) »), fraîcheur, et **raison** si éteinte
  (Reddit banni, CryptoCompare quota, DXY/COT désactivés ADR-018 P2).
- **Honnêteté (Axe #1)** : rappel « **toutes les sources à parts égales** », « accord ≠ fiabilité »,
  **zéro % d'influence**. Vue = **contexte**, pas edge (NO-GO intact).

**Données 100 % réelles, zéro backend touché** : `source_health` + `signals24h` (dernier swing)
via les hooks existants `useSourceHealth` + `useDashboardKpis`.

**Fichiers** : `src/sources/orbital.ts` (modèle PUR roster + `buildOrbitalModel`, **19 assertions
prouvées par exécution**) · `components/cosmic/cosmic-orbital.tsx` (soleil + orbite + satellites en
positions absolues sur carré FIXE 320×320, pas de SVG → rendu stable mobile) · `app/observatoire.tsx`
(page + bascule) · `app/_layout.tsx` (route enregistrée, header sombre) · `app/(tabs)/sources.tsx`
(bouton d'entrée). tsc + eslint + bundle iOS verts.

**Note débogage** : la trader « ne voyait pas la page » au 1er essai = **cache Expo Go** (Reload
complet / kill+relance a réglé) — pas un bug. Rendu device **validé** par la trader.

**Reste possible (NON fait)** : satellites flash (carnet/flux) volontairement **exclus** (l'orbite
montre le système OSINT swing, pas la microstructure « hachée »). [La **v2 « deux soleils »** a été
livrée le 2026-06-21 → cf. session dédiée ci-dessous.]

## 🗓 Session 2026-06-21 — Observatoire v2 « relations » : deux soleils (commit `be86711`)

Reprise du « reste possible » de la session Observatoire : la **v2 « deux soleils »** (façon
maquette `tik toggle orbital relations.html`, **lue** pour l'occasion).

**Livré** — un **toggle « ◐ Par actif / ✦ Relations »** en haut de `/observatoire` :
- **Vue Relations** : **BTC (soleil haut) + GOLD (soleil bas) ensemble**. Sources propres à chaque
  actif de son côté, et au **centre le « pont »** = la/les source(s) qui alimentent les DEUX. Aujourd'hui
  **une seule source partagée : Google News** (seule présente dans les deux rosters). Chaque **trait**
  relie une source à son/ses soleil(s), **couleur = santé** de la source. Tap → texte verbatim.
- **Fait structurel honnête mis en avant** : Google News a **deux faces indépendantes** (santé + texte
  propres par actif : `google_news_btc` vs `google_news_gold`) → montrées **côte à côte** au tap, et
  les **deux traits** du pont portent chacun la santé de leur face. Pastille du pont en **bleu neutre**
  (pas une face arbitraire).
- **Honnêteté (Axe #1)** : la maquette « relations » montrait des sources que Tik **n'a pas** (Whales/
  ETF/Stables, DXY-CPI-US10Y comme « partagées ») + des « % d'influence » → **version restreinte au
  vrai roster, zéro % inventé**, rappel « parts égales », « accord ≠ fiabilité ».

**Fichiers** : `src/sources/relations.ts` (modèle PUR par-dessus `buildOrbitalModel` : partition
btcOnly/goldOnly/shared, **18 assertions prouvées par exécution** via `npx tsx` — dont l'indépendance
des deux faces du pont, l'invariant `btcOnly+shared=sources`, le flash ignoré) · `components/cosmic/
cosmic-relations.tsx` (deux soleils + traits SVG `Line` + nœuds en coordonnées **fixes 320×480** calés
sur les mêmes points → rendu stable mobile + panneau détail/pont au tap) · `app/observatoire.tsx`
(toggle de vue). **Données 100 % réelles** (mêmes hooks `useDashboardKpis` + `useSourceHealth`), **zéro
backend touché**, réversible (`main` intact). tsc + eslint + bundle iOS verts.

**Non vérifié** : rendu pixel sur device (validé tsc/eslint/bundle/18 assertions, pas le pixel — à
confirmer par la trader : Expo Go → Reload → onglet **Sources** → bouton « ✦ Vue orbitale » → toggle
**✦ Relations**).

## Reste à faire (OPTIONNEL — rien de bloquant)
1. **Polices custom** Fraunces / JetBrains Mono / Manrope (« bout 4 ») — DIFFÉRÉ : `npm install @expo-google-fonts/*` + `useFonts` ⇒ **redémarrage Metro** ⇒ l'URL du **tunnel ngrok anonyme change** ⇒ la trader doit **rescanner** le QR dans Expo Go. À faire en prévenant.
2. **Sparklines par source** (Sources) — IMPOSSIBLE en l'état : pas de série historique par source exposée → exigerait un **ajout backend** (soumis à « pas d'ajout sans manque mesuré »).
3. ~~**Cartes Macro** (régime/liquidité/taux) encore en **cartes** — pourraient passer en jauges~~ → **FAIT 2026-06-20** : composant réutilisable `components/cosmic/cosmic-gauge.tsx` (reprend la géométrie corrigée sweep-flag 1 de `cosmic-hit-rate`) + jauge demi-cercle ajoutée en headline des 3 cartes (régime = z-score liquidité Fed ; mondiale = z-score global ; taux Fed = proba dominante prochaine réunion FOMC). Détail chiffré conservé dessous. Honnête (Axe #1 : visualise un chiffre objectif, aucune prédiction). tsc/eslint/bundle verts.
4. ~~**Plus** : cartes « hit-rate par tranche veracity » + « stats LLM » thémées~~ → **FAIT 2026-06-19** (cosmétisées, tokens Cosmic ; « par veracity » → « par accord »).
5. ~~**Vue orbitale** : version **qualitative** (sans chiffres d'influence)~~ → **BOUT 1 FAIT 2026-06-20 (soir)** : page `/observatoire`. **v2 « deux soleils » FAIT 2026-06-21** (toggle Relations : BTC+GOLD + pont Google News, commit `be86711` — cf. session dédiée). Vue orbitale **complète**.
6. **Polymarket journalier** : l'ingester exclut volontairement l'intraday « up or down » (5 min = bruit) → marchés **swing** seulement (échéance affichée). Le journalier = **ajout backend assumé** si un jour demandé.

## Maquettes HTML (vérité visuelle) — `docs/adr/design_phase2/`
`tik mockup gamma.html` (Signals/Sources/Calendar — **lue**) · `tik mockup enrichi.html` (Orbital/Watchlist/Profil — **lue**) · `tik orbital view.html` + `tik toggle orbital relations.html` (orbital — **lues 2026-06-20** ; ⚠ elles contiennent des « % d'influence » + des sources que Tik n'a pas (Whales/CoinGlass payant, ETF Gold, Silver) → **version livrée volontairement honnête**, cf. session Observatoire). Tokens CSS = `:root` (déjà transposés dans `cosmic.ts`).

## Prévisualisation
**Metro tourne sur le VPS** en tunnel **ngrok** (`npx expo start --tunnel`, port 8081, URL **anonyme** `…exp.direct` — change à chaque restart). La trader : **Expo Go → secouer → Reload**. Pas besoin de commit pour prévisualiser (Metro sert le working tree).

## Vérifs OBLIGATOIRES après toute modif UI (toujours faites, toujours vertes ici)
```bash
cd /opt/tik/dashboard
npx tsc --noEmit                                   # exit 0
npx eslint <fichiers touchés>                      # exit 0
curl -s -o /tmp/b.txt -w "%{http_code}\n" \
  "http://localhost:8081/node_modules/expo-router/entry.bundle?platform=ios&dev=true" --max-time 175
grep -icE "Unable to resolve module|Module not found" /tmp/b.txt   # doit être 0
```
⚠ Le bundle renvoie HTTP 200 même quand c'est bon ; **ne PAS** grep large (« Cannot find » / « SyntaxError » matchent du code de lib = faux positifs). Utiliser le pattern ci-dessus.

## Workflow
On bosse **bout par bout, validé par la trader**, **commit isolé** à chaque étape (réversible), **push** sur `refonte-cosmique`. Pas de Mac (la trader code via SSH/VS Code sur le VPS). Engagements 13bis actifs (doute, mesurer, pour/contre, transparence, vérifier).

---

## Contexte / demande de la trader (Théa)

Refonte de l'interface du dashboard Expo pour qu'elle soit **agréable, ergonomique,
lisible** (pas forcément « débutant » mais bonne UX/UI), dans une **identité visuelle
cosmique** (direction γ). Le « 2027 » du prompt initial était **arbitraire** → on le
fait **maintenant**, par **bouts validés un par un** (jamais un gros bloc).

## Décisions ACTÉES (ne pas re-litiger sans demande)

1. **Approche = refonte progressive convergente** : on fige la structure cosmique une
   fois, on **reskine les composants déjà débuggés**, zéro backend touché. PAS de
   big-bang (casserait du code testé + redessinerait du vide).
2. **BTC + GOLD uniquement.** Silver, EUR/USD tradable, index « Stress 0-100 », et
   l'orbitale « influence chiffrée » = **RETIRÉS de la v1** (données inexistantes /
   sur-vente → Axe #1). Composants extensibles : ajouter Silver plus tard = trivial.
3. **Navigation = drill-down** : vue d'ensemble propre + on **tape un élément pour
   ouvrir une page dédiée** (pas tout entassé en cartes sur un scroll). Règle d'or :
   *ce qui sert à décider reste en surface ; la profondeur est derrière un tap.*
4. **Vue Signals = port cosmique de l'ANCIEN onglet Signals** (que la trader aimait) :
   filtres + pastilles + liste. PAS de cartes BTC/GOLD résumées en haut (doublon retiré).
5. **Garder Top Headlines** (le tag BULL/BEAR aide la trader) ; Breaking news → futur
   bandeau d'alerte compact (PAS fusionner bêtement).
6. **« Veracity » renommé « accord » dans l'UI** (cf. audit ci-dessous, anomalie A9).

## Identité visuelle (palette γ) — `dashboard/constants/cosmic.ts`

Fond `#0a0c14` / profond `#06070d` / carte `#131826` ; accent ambre `#f5b042` ;
long `#6ec5a2` / short `#e87a7a` / neutral `#e8b86b` / macro `#7d9ed3`.
Polices : pour l'instant **serif/mono système** (rendu cosmique ~80 %). Vraies polices
**Fraunces / JetBrains Mono / Manrope** = bout 4 (`expo-font` est installé).

## Fichiers (branche refonte-cosmique)

**Créés :**
- `dashboard/constants/cosmic.ts` — palette γ + `directionMeta()` + `sunColor()`
- `dashboard/components/cosmic/cosmic-background.tsx` — fond SVG (dégradé radial + étoiles), react-native-svg (déjà installé)
- `dashboard/components/cosmic/cosmic-signal-card.tsx` — **carte riche** (drivers + contre-scénario) → destinée au **haut de la page détail (bout 2)**, pas encore rendue
- `dashboard/components/cosmic/cosmic-signal-row.tsx` — ligne de la liste Signals (tap → détail)
- `dashboard/app/cosmique.tsx` — **écran Signals cosmique (bout 1)**
- `dashboard/src/signals/stability.ts` — `computeDirectionStability()` (pastille GOLD swing)

**Modifiés :**
- `dashboard/app/_layout.tsx` — route `cosmique` enregistrée (header dark)
- `dashboard/app/(tabs)/index.tsx` — bouton **teaser** « ✨ Aperçu refonte cosmique » en haut de l'onglet Marché (accès temporaire ; sera remplacé par la promotion en vrai onglet au bout 5)

## Comment prévisualiser (sur l'iPhone de la trader)

Metro tourne **sur le VPS** en tunnel ngrok (port 8081, `--tunnel`, lancé le 16/05).
Dans Expo Go (app Tik déjà connectée) : **secouer → Reload** → onglet **Home / Marché**
→ bouton orange **« ✨ Aperçu refonte cosmique »** en haut → écran Signals cosmique.
Tap une ligne → page détail (encore en ancien style ; cosmique = bout 2).

## Vue Signals cosmique (bout 1 — FAIT) — ce qu'elle contient

- Filtres : `Tous/BTC/GOLD` · `Flash/Swing/Macro` · `24h/5j/30j` + statut **Live**
- Pastille **« Court terme BTC : calme/haché »** (stabilité flash, BTC only — pas de flash GOLD)
- Pastille **« GOLD swing : stable/hésitante »** (`computeDirectionStability`, fenêtre 48h)
- Liste cosmique : sens + actif + horizon + badges AFN/macro + `conv/accord/sources/±ampl`
- ⓘ d'explication (glossaire in-app) sur `conv/accord/horizon`
- Tap ligne → page détail (drill-down)

## Page détail cosmique (bout 2 — FAIT, validé trader 2026-06-16) — ce qu'elle contient

- **Route DÉDIÉE** `app/signal-cosmique/[id].tsx` — NE PAS confondre avec `app/signal/[id].tsx`,
  resté **intact en thème clair**. Pourquoi : il n'existe qu'UNE route détail ; la passer en
  cosmique « en place » faisait que les ANCIENS onglets encore clairs (Signals/Watchlist/Alerts)
  ouvraient aussi le détail sombre (**bug remonté par la trader**). Solution : `cosmic-signal-row`
  + `cosmic-signal-card` poussent vers `/signal-cosmique/...` ; les anciens onglets gardent
  `/signal/...`. Route enregistrée dans `_layout.tsx` (header sombre). Au bout 5 (promotion du
  cosmique en vrai onglet), on consolidera les deux routes.
- **Héros** = `CosmicSignalCard variant="detail"` (nouveau prop) : non cliquable, **sans** le
  teaser evidence/contre-scénario/lien — ces sections sont rendues EN ENTIER dessous (pas de
  doublon). Le variant `summary` (défaut) garde le comportement riche+cliquable.
- Sous le héros : flags AFN + proximité macro (cosmiques **inline**), bouton Suivre, **track
  record** (logique 3 états ✓/≈/✗ + points MT5 **intégralement préservée**), hypothèse, hypothèse
  LLM/template (ADR-012), contre-scénarios, evidence, triggers décisionnels + contexte technique
  (collapsible cosmique inline), advisory, dates/ID.
- **Relief « 3D » des titres** (demande trader) : `TitleShadow.strong/.soft` dans
  `constants/cosmic.ts` — ombre portée RN (UNE seule ombre possible, donc pas d'extrusion
  multi-couches). Appliqué aux gros titres héros (actif + direction) + titres de section + titre
  « Signals ». Ajustable en 1 endroit (2 valeurs).
- Badges AFN/macro + collapsible **ré-implémentés en cosmique inline** : les composants partagés
  (`AntiFakeNewsBadge`, `NearMacroBadge`, `Collapsible`) dépendent du thème clair/sombre de
  l'appareil → ils jureraient sur le fond sombre forcé. Légère duplication de logique triviale, assumée.

## Bout 3 (page Macro) — FAIT (validé 2026-06-16)

Route dédiée `app/macro-cosmique.tsx` + 3 cartes cosmiques (`cosmic-macro-regime-card`,
`cosmic-global-liquidity-card`, `cosmic-rate-probabilities-card`) réutilisant les hooks
existants (`useMacroRegime`, `useRateProbabilities`) — zéro backend touché. **Bandeau
contexte macro** compact en haut de la liste Signals → tape vers la page Macro. Lien vers
le calendrier `/macro` (thémé) en bas. + polish visuel (cf. ci-dessous).

## Polish visuel — FAIT (suite retour trader « pas lisible / titre pas envie »)

`constants/cosmic.ts` : contraste des textes remonté (textDim 0.62→0.78, textFaint 0.38→0.56),
accent plus lumineux (`#ffc15e`), cartes/bordures mieux définies. **Titres** en **serif système**
(`serifTitleFamily`) + **halo ambré** (`TitleShadow.glow`) sur les gros titres (pages + héros).

## Bout 5 (navigation) — FAIT (validé 2026-06-16, choix trader « garder mes 6 onglets, tout cosmique »)

- L'écran cosmique est devenu le **vrai onglet Signals** : `app/cosmique.tsx` → `app/(tabs)/signals.tsx`
  (ancien Signals thémé remplacé). Route d'aperçu `/cosmique` + **bouton teaser** du Home **retirés**.
- **Barre d'onglets en sombre cosmique** (`app/(tabs)/_layout.tsx`, accent ambre). On a **gardé les 6
  onglets** (Home / Signals / Watchlist / Carnet / Alerts / Config) — PAS le regroupement 8→5 du plan
  initial (devenu inadapté depuis l'ajout du Carnet).
- **Thème sombre forcé GLOBAL** (`hooks/use-color-scheme.ts` + `.web.ts` renvoient `'dark'`) +
  **`Colors.dark` reteinté cosmique** (`constants/theme.ts`) → tous les écrans encore « thémés »
  (Home/Watchlist/Carnet/Alerts/Config/login) adoptent la palette cosmique d'un coup, **sans réécrire
  chaque composant**. ⚠ `tint` gardé **bleu** (pas ambre) : des boutons ont du texte blanc hardcodé
  (blanc-sur-ambre = illisible). Réversible (restaurer les 2 hooks + le bloc `Colors.dark`).

## Bouts RESTANTS

4. **Vraies polices** Fraunces / JetBrains Mono / Manrope — **DIFFÉRÉ** (« on décide plus tard »).
   ⚠ nécessite `npm install` + **redémarrage Metro** → l'URL du tunnel ngrok **anonyme** change →
   rescan du QR dans Expo Go.
6. **Polish cosmique par écran** (long tail) : Home/Watchlist/Carnet/Alerts/Config sont désormais
   en dark cosmique (palette `Colors.dark`) mais gardent leur layout thémé — les passer au traitement
   cosmique complet (fond dégradé `CosmicBackground`, cartes `Cosmic.card` distinctes, titres serif/halo)
   reste à faire écran par écran selon ce que la trader veut prioriser. Le Home a ~14 cartes.

## Vérifications à relancer après toute modif UI

```bash
cd /opt/tik/dashboard
npx tsc --noEmit                 # doit sortir exit 0
npx eslint <fichiers touchés>    # doit sortir exit 0
# bundle iOS (compile toute l'app comme l'iPhone) :
curl -s -o /tmp/b.txt -w "%{http_code}\n" \
  "http://localhost:8081/node_modules/expo-router/entry.bundle?platform=ios&dev=true" --max-time 170
grep -iE "Unable to resolve module|Module not found" /tmp/b.txt || echo "bundle propre"
```

---

# Audit veracity + backtests (analyse menée le 2026-06-15)

La trader a demandé si les signaux à veracity basse sont « vrais » et s'il faut les
enlever. **Réponses mesurées :**

- **Aucun signal sous veracity 0.70** (plancher structurel du moteur, ADR-026). Min =
  0.700 sur les 3 séries. Donc « enlever sous 70 » = ensemble vide.
- **La veracity NE prédit PAS la justesse.** Backtest (horizon 5j) : le plancher 0.70
  (39.2 % hit) fait **MIEUX** que 0.90 (34.5 %) et 0.95 (32.6 %). Non-monotone.
- **B swing-only** (`measure_post_fix_hit_rates --signal-horizon swing --horizon-days 5`) :
  à veracity ≥ 0.85 **et** ≥ 0.90, **Tik PERD contre « Always SHORT » (p=0.000)** →
  NO-GO directionnel confirmé proprement. **Filtrer par veracity ne crée pas d'edge.**
- **Verdict : NE PAS enlever les signaux à veracity basse.** (Données + ils portent une
  info : « sources en désaccord → pas de vue claire ».)

## Audit des sources qui alimentent la veracity

⚙️ Veracity = **dispersion NON pondérée** des biais sources (ADR-004). Donc la
crédibilité par source (0.65→0.90) **n'a aucun effet** sur la veracity (anomalie A12).

**BTC swing = 2/4 sources vivantes** (vérifié via TTL Redis, clés en `.btc` minuscule) :
- ✅ Fear & Greed (`tik.sentiment.fear_greed`) — vivant ; contrarian → écrase la veracity au plancher (par design)
- ✅ Google News (`tik.sentiment.google_news.btc`) — vivant
- ❌ CryptoCompare — MORT (quota 100/mois, Bug 15 ; reset ~1er du mois ; clé présente dans `.env`)
- ❌ Reddit — MORT (ban IP, Bug 11)
- 🔕 CoinGecko — gaté OFF (shadow, redondant F&G)

**GOLD swing = 2/4** : ✅ Google News + ✅ GDELT (`tik.sentiment.gdelt.gold`, rate-limited 429 mitigé) ; 🔕 DXY + COT désactivés (mesurés INVERSÉS en bull, ADR-018 P2).

**Flash BTC** : orderbook + aggression Binance (flippent sans edge → pastille « haché »).

## Vérité empirique (à ne pas maquiller)

Toutes les sources actuelles = **sentiment retardé, même famille** → en ajouter
**dilue** l'edge, ne le crée pas (CLAUDE.md « la vérité empirique »). Le levier réel =
**familles non-sentiment**, déjà en shadow : **dérivés Binance (ADR-023)** + **flux ETF
(ADR-024)**, à **MESURER ~2026-06-17** avant tout enrôlement (règle « pas d'ajout sans
manque mesuré »).

## Recherche sources (WebSearch 2026)

- Hygiène sentiment : **CryptoPanic** (free, **slot `TIK_CRYPTOPANIC_API_KEY` VIDE dans
  `.env`** = anomalie A11), Santiment, LunarCrush — *mais ça reste du sentiment*.
- Non-sentiment : **CoinMarketCap** dérivés sans clé (OI/funding) — *mais on a déjà
  Binance derivatives en shadow*.

## Anomalies trackées (cumul session)

- A1–A5 : erreurs du prompt initial (Vague 1 — sources déjà faites/payantes : ETF BTC
  = ADR-024, liquidité = ADR-028, CoinGlass payant ; « 11 services » ≠ 5 ; UI-2027 ;
  mockups HTML jamais fournis)
- A6 : signal de trading enterré en position #13 sur la Home → corrigé (signal-first)
- A7 : Top Headlines vs Breaking → PAS un doublon (bull/bear utile) → gardés
- A8 : Silver/Stress/orbitale-influence = données absentes → retirés v1
- A9 : « Veracity » = nom trompeur (mesure l'accord, pas la vérité) → **renommé « accord »**
- A10 : clé F&G sans suffixe entité (`tik.sentiment.fear_greed`) — cosmétique
- A11 : `TIK_CRYPTOPANIC_API_KEY` vide (source news pré-câblée, jamais branchée)
- A12 : veracity NON pondérée → crédibilité par source sans effet (faille design, mais
  inutile à corriger : veracity non prédictive — Axe #1)

## Reste à faire / NON vérifié

- Refonte UI bouts 2 → 6 (cf. ci-dessus).
- Valeur prédictive **individuelle** par source (FG vs News séparés) — non mesurée.
- Mesure des shadows non-sentiment (dérivés/ETF) ~2026-06-17 = **le vrai levier d'edge**.
- CryptoPanic non branché (ce serait un *ajout* → soumis à « manque mesuré » + sentiment).
- Backtests limités à ~41 j de couverture prix, **régime baissier** → dépendants période ;
  fenêtres chevauchantes → pas de significativité fine (cf. mémoire `measurement-overlapping-returns`).

## Prochaines étapes possibles (options C / D / E proposées à la trader)

La trader doit choisir. Les trois sont valides ; (c) et (e) recommandées.

### (C) Reprendre la refonte UI — bout 3 : page Macro [RECOMMANDÉ]
Bout 2 (page détail cosmique) **FAIT et validé** (cf. section dédiée plus haut). Suite directe =
bout 3 : déménager les cartes liquidité Fed/mondiale **riches** (déjà sur la Home actuelle) vers
une page Macro cosmique, avec un **bandeau contexte** compact en haut de Signals qui tape vers
elle. PAS d'index « Stress » (donnée absente). Puis bouts 4→6 (cf. plus haut).

### (D) Backtest de la valeur prédictive INDIVIDUELLE de chaque source
But : mesurer si Fear & Greed, Google News, GDELT… pris **séparément** ont un pouvoir
prédictif (corrélation biais source → rendement futur), pour savoir laquelle (s'il y en
a une) mérite plus de poids — vs lesquelles ne sont que du bruit.
- ⚠️ **Pas de script clé-en-main pour le sentiment.** `backtest_numeric_sources.py`
  existe mais pour les **sources numériques** (DXY/COT). `measure_coingecko_predictive.py`
  fait ce type de mesure pour CoinGecko → **s'en inspirer** pour bâtir l'équivalent
  par-source sentiment (lecture seule DB + klines prix).
- Cadre rigueur obligatoire : fenêtres **non chevauchantes**, comparaison vs
  **Always SHORT** (pas Random), N par source, IC/Spearman (cf. mémoires
  `measurement-rigor-controls`, `measurement-overlapping-returns`).
- Caveat honnête attendu : vu le NO-GO + « même famille sentiment », il est **probable**
  qu'aucune source sentiment ne ressorte prédictive. À mesurer quand même avant d'affirmer.

### (E) Mesurer les shadows NON-SENTIMENT — le vrai levier d'edge [RECOMMANDÉ sur le fond]
C'est là qu'un edge peut exister (familles différentes du sentiment). Deux familles
**déjà collectées en shadow**, jamais branchées, à mesurer **~2026-06-17** :
- **Dérivés Binance (ADR-023)** : `python -m tik_core.scripts.measure_btc_derivatives`
  (funding / open interest / long-short ratio). Mémoire `binance-derivatives-shadow-live`.
- **Flux ETF spot BTC (ADR-024)** : `python -m tik_core.scripts.measure_btc_etf_flows`
  (inflow/outflow net quotidien, SoSoValue). Mémoire `btc-etf-flows-shadow-live` (IC
  préliminaire ~0, à confirmer).
- Règle absolue : **mesurer ≥ 2 semaines (IC / hit rate / gain apparié vs Always SHORT)
  AVANT tout enrôlement** sur le `combined_bias` (CLAUDE.md « la vérité empirique »).
- ⚠️ Lancer ces scripts **lecture seule** (ils lisent Redis/DB, ne mutent rien) ;
  vérifier d'abord `crontab -l` + les logs `measure-*-cron.log` (mémoire
  `prefer-check-before-rerun` : ne pas re-mesurer pour rien).

**Recommandation :** (C) pour continuer l'UI commencée, (E) sur le fond car c'est le seul
levier d'edge mesurable. (D) utile mais probablement un cul-de-sac (sentiment).
