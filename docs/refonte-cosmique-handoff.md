# Passation — Refonte UX « cosmique » + audit veracity (2026-06-15)

> **Pour la prochaine instance Claude** : ce document = l'état exact où on en est.
> Lis-le en entier, puis lis `CLAUDE.md` (contexte projet) et la mémoire
> `layout-ux-overhaul-deferred`. Tout le travail UI vit sur la branche
> **`refonte-cosmique`** (main intact = 100 % réversible).

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

## Bouts RESTANTS (Passe 1)

2. **Page détail en cosmique** — y placer `CosmicSignalCard` en haut + le reste
   (hypothèse, contexte technique poids 0, evidence, contre-scénarios, track record).
3. **Page Macro** — les cartes liquidité Fed/mondiale **riches** (qui existent déjà sur
   la Home actuelle) y déménagent ; un **bandeau contexte** compact en haut de Signals
   tape vers cette page. (PAS d'index « Stress » : donnée absente.)
4. **Vraies polices** Fraunces / JetBrains Mono / Manrope (expo-font installé).
5. **Regrouper 8 → 5 onglets** (`Signals / Sources / Watch / Calendar / Profil`) +
   **promouvoir** `cosmique.tsx` en vrai onglet Signals + retirer le bouton teaser.
   (Profil = regrouper Config + About + stats.)
6. **Sources / Calendar / Watch / Profil** en cosmique.

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

## Prochaine étape recommandée

(c) reprendre la refonte au **bout 2 (page détail cosmique)**, et/ou (e) préparer la
**mesure des shadows non-sentiment** (le seul levier d'edge mesurable).
