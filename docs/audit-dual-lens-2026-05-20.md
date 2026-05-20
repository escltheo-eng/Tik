# Audit dual-lens Tik — backend (signaux) + frontend (UX) — 2026-05-20

**Contexte** : J-4 du trading manuel (2026-05-24). Audit demandé par
l'utilisatrice sous la consigne « avec paranoïa et sans paranoïa sur
absolument tout, documenté/démontrable ». Méthodologie : pour chaque
élément (slice de signal côté backend, élément d'UI côté frontend), deux
lectures de la même réalité —

- **Sans paranoïa** : ce que ça donne / ce que ça veut dire (lecture optimiste).
- **Avec paranoïa** : significativité, gain (l'argent), confonds, échantillon,
  ce qui peut induire en erreur (lecture sceptique).

Tout est reproductible : backend via `backtest_dual_lens.py`, frontend via
lecture du code dashboard cité en `fichier:ligne`. Lecture/mesure seule côté
backend (zéro modif pipeline) ; côté frontend, seules les **corrections de
faits** ont été appliquées (cf. §3).

---

## 1. Backend — les signaux (31 slices, `backtest_dual_lens.py`)

Données post-fix Bug N=2 (2026-05-17 20:47 →), horizons mûrs (flash 1h,
swing 6h/24h). Le swing 5j (mesure décisive) n'existe pas avant le 2026-05-22.

| Slice (exemples) | Sans paranoïa | Avec paranoïa |
|---|---|---|
| Flash BTC @1h overall | 37,9 % bat random | p=0,026 ✗Bonferroni · gain− → **FRAGILE** |
| Flash BTC short/long | ~14 % | sous random · pas d'edge directionnel |
| Swing BTC @6h overall | 42,6 % bat random | ✓Bonf mais **gain−** → FRAGILE |
| Swing BTC @6h `cb_status=ok` | 37,8 % bat random | **non-sig** (p=0,27) |
| Swing BTC @24h short | 17,7 % | **sous** random (gain+ = beta baissier) |
| Swing BTC veracity≥0,85 | varie | non-sig OU gain− selon horizon |
| GOLD @24h (tous) | sous random | gain global −0,49 % |

**Verdict backend démontré** : sur les **31 slices**, **aucun n'est
simultanément `bat random` + significatif après Bonferroni + `gain+`**. Les
« wins » sont des signaux *neutral* (gain− par construction) ; les
directionnels sont au niveau/sous random, leurs petits gains short = suivre la
tendance baissière (*beta*, pas *alpha*). **Tik n'a aucun edge directionnel
robuste mesurable** sur les données disponibles.

Sous-conclusions :
- **Filtre veracity ≥ 0,85** : neutre sur swing BTC (le « dégrade » initial
  était un artefact flash-inversé + bruit GOLD). Pas un edge, pas nuisible.
- **Anti-fake-news (`ok` vs `degraded`)** : *sans paranoïa* `ok` short touche
  ~2× mieux ; *avec paranoïa* inconcluant (multiple-testing : @6h ne survit
  pas à Bonferroni ; redondant avec veracity ≥ 0,85 — degraded tous à 0,78 ;
  gain s'inverse à 24h).
- **Données pré-fix contaminées** (CryptoCompare manquant → cross-validation
  N=2 buggée) → tout backtest pré-fix inexploitable, dont les anciens chiffres
  « SHORT BTC 63 % » et « GOLD 4,8 % ».

**Reproductible** : `python -m tik_core.scripts.backtest_dual_lens
--signal-horizon swing --entity BTC --horizon-hours 6` (ou `--horizon-days 5`
le 27/05).

---

## 2. Frontend — l'UX/UI du dashboard

Question paranoïaque : *qu'est-ce qui pourrait faire croire à une débutante
que Tik est plus fiable qu'il ne l'est, et lui coûter de l'argent ?*

| Élément (fichier) | Sans paranoïa | Avec paranoïa |
|---|---|---|
| « Conviction OSINT » + « Veracity » en gros ([signal/[id].tsx:267](../dashboard/app/signal/[id].tsx#L267)) | métriques chiffrées, sous-titres honnêtes | mots « Veracity »/« Conviction » + gros % vert → fausse impression de fiabilité (aucune valeur prédictive prouvée) |
| Scores crédibilité dans Evidence ([signal/[id].tsx:396](../dashboard/app/signal/[id].tsx#L396)) | transparence par source | recalibration a pénalisé orderbook/aggtrades à **35 %** (artefact cosmétique) — incohérent avec le glossaire (0,90) |
| Badge anti-fake-news ([anti-fake-news-badge.tsx](../dashboard/components/dashboard/anti-fake-news-badge.tsx)) | warning-only | ✅ **honnête** : pas de sceau vert « vérifié » qui créerait une fausse confiance |
| Hypothèse LLM ([signal/[id].tsx:329](../dashboard/app/signal/[id].tsx#L329)) | contexte riche 6 sections | prose assurée → autorité non méritée sur un signal sans edge |
| Jauge veracity Home ([veracity-gauge.tsx](../dashboard/components/dashboard/veracity-gauge.tsx)) | sous-label « Concordance forte » (honnête) | titre « Veracity » + vert ≥85 % → lecture « bon/go » par une débutante |
| HitRateCard ([hit-rate-card.tsx](../dashboard/components/dashboard/hit-rate-card.tsx)) | calibration empirique, code couleur | calcule sur 30j = pré-fix contaminé + post-fix immature, affiché comme % propre ; caveats en commentaire dev, **pas montrés à la trader** |
| Glossaire `gardeFou2bis` ([glossary.ts](../dashboard/src/glossary.ts)) 🔴 | rappelle les règles | **instruisait** « observer SHORT BTC 63 % » → un edge FAUX (contaminé). **Corrigé** §3 |
| Carte discipline mini-F1 ([index.tsx:165](../dashboard/app/(tabs)/index.tsx#L165)) | 5 puces de discipline solides | citait « GOLD 4,8 % » contaminé (règle OK, chiffre faux). **Corrigé** §3 |

**Verdict frontend** :
- *Sans paranoïa* : dashboard soigné, transparent (evidence, contre-scénarios,
  tooltips, badges warning-only) → outil d'aide à la décision pro.
- *Avec paranoïa* : l'UI **parle le langage visuel d'un système validé et
  confiant** (gros % « Veracity/Conviction », track record ✓, prose LLM)
  alors qu'**aucun edge n'est démontré** → risque de sur-confiance / sur-sizing
  pour une débutante. Point positif notable : le badge AFN est honnête
  (warning-only, pas de faux sceau vert).

---

## 3. Corrections de faits appliquées (2026-05-20, dashboard 0.5.17)

Seules les **corrections de faits** (≠ refonte UX) ont été faites, car le
dashboard affichait des chiffres contaminés comme des vérités, dont un qui
**instruisait** un pari :

- `glossary.ts` `gardeFou2bis` : retrait du « SHORT BTC 63 % » et « GOLD 4,8 % »
  comme edges → remplacés par « aucun edge directionnel robuste démontré à ce
  jour, chiffres antérieurs contaminés (Paquet 33), mesure fiable au 27/05 ».
- `app/(tabs)/index.tsx` carte discipline : « pas de GOLD (4,8 % hit) » →
  « pas de GOLD (aucun edge directionnel mesuré) ». La règle reste, le chiffre
  faux part.

Validé : `tsc --noEmit` exit 0, `eslint` exit 0.

---

## 4. Différé à la refonte UX de fin de dev (documenté, NON codé)

Cohérent avec la décision utilisatrice (refonte UX complète en fin de dev) +
« ne pas coder de feature sans demande » :

1. Mots « Veracity »/« Conviction » trop affirmatifs → envisager un libellé qui
   ne suggère pas une fiabilité (ex. « concordance sources » / « magnitude
   biais ») et un disclaimer « pas d'edge prouvé / en calibration ».
2. HitRateCard → afficher un caveat visible (« inclut données pré-fix / fenêtre
   courte ») tant que la mesure 5j post-fix du 27/05 n'a pas tranché.
3. Scores crédibilité penalisés (35 %) → soit afficher le score statique tant
   que la recalibration tourne sur données contaminées, soit un tooltip
   « score en recalibration ».
4. F1 (bande feu pré-trade) déjà tracé dans l'audit UX du 2026-05-17.

---

## Conclusion

**Backend et frontend racontent la même histoire en double lentille** : *sans
paranoïa*, Tik paraît avoir des edges et une UI confiante ; *avec paranoïa*,
**aucun edge directionnel robuste n'est démontré** et l'UI sur-communique la
confiance. La seule posture justifiée par la donnée reste le **sizing 1 %**, et
la mesure décisive est le **swing 5j post-fix du 2026-05-27**. Les chiffres
contaminés qui instruisaient un comportement ont été corrigés ; le reste de
l'alignement UX↔réalité est documenté pour la refonte de fin de dev.

---

## Annexe — Audit cohérence / intégrité / fiabilité des données (2026-05-20, sans paranoïa)

Recherche systématique des **conflits, anomalies et problèmes réels** (front +
back), lecture/mesure démontrable, arguments pour/contre → consensus.

### Backend — intégrité des données : ✅ SAINE (13 invariants, 0 violation)

Mesuré sur l'ensemble des signaux en DB :

| Invariant | Résultat |
|---|---|
| Directionnels (long/short) avec conviction < seuil 0,30 | **0** |
| `tripped` avec direction ≠ neutral (AFN doit forcer neutral) | **0** |
| veracity hors [0,70 ; 0,95] | **0** (paliers exacts : 0.70/0.78/0.85/0.90/0.95) |
| confidence hors [0 ; 1] | **0** |
| expiry ≤ timestamp | **0** |
| champs critiques NULL (direction/conf/verac/hypothèse) | **0** |
| ids dupliqués | **0** |
| neutral avec conviction ≥ 0,30 hors tripped | **0** |
| `circuit_breaker_status` hors {ok, degraded, tripped} | **0** |
| `sources_count` ≠ longueur du tableau evidence | **0** (coïncidence parfaite) |
| evidence/triggers vides | **0** |
| trous de cadence > 90 min (downtime scheduler) sur 5 j | **0** |
| TTL réel par horizon (DB) | flash 1,01h · swing 168,01h = cohérent code (`EXPIRY_BY_HORIZON`) |

**Consensus backend** : la donnée signal est **internement cohérente et fiable**.
Aucune anomalie structurelle. Runtime : uniquement des warnings
`ollama_error ReadTimeout` occasionnels (LLM timeout → fallback template géré par
le circuit breaker ADR-012, `consecutive_failures=1`). Pas un bug.

États de fiabilité connus (documentés, pas des bugs) : Reddit IP-banni (swing BTC
à 3 overlays sentiment), GDELT 429 intermittent (GOLD parfois 2 overlays),
recalibration qui pénalise les scores affichés (cosmétique post-ADR-018).

### Frontend — 1 conflit factuel trouvé et corrigé

| Conflit | Pour (problème) | Contre (mineur) | Verdict |
|---|---|---|---|
| `glossary.ts` horizon : « swing (TTL **4h**) » alors que code = 7j (DB 168h) | tooltip faux, la trader croit le signal expiré en 4h | détail tooltip, sens « heures-jours » conservé | **Corrigé → « TTL 7j »** (dashboard 0.5.18) |

Vérifs cohérence front↔back **OK** : HitRateCard « swing 5j » = backend
`HORIZON_MEASURE_HOURS` (5j) ✓ ; track record « swing 1h/6h/24h/5j » ✓ ;
sélecteurs horizon = horizons backend ✓.

### Consensus global

**Tik est techniquement sain et cohérent** : intégrité des données parfaite (13
invariants), pipeline stable (zéro downtime), front↔back cohérent à un tooltip
près (corrigé). Les seuls « problèmes » résiduels ne sont pas des bugs mais des
**caractéristiques connues** (pas d'edge démontré, Reddit/GDELT dégradés,
recalibration cosmétique) déjà documentées et tracées. Pour de bonnes
performances : la fiabilité **technique** est acquise ; la fiabilité
**prédictive** (l'edge) reste à établir le 2026-05-27.

---

## Annexe 2 — Modes de défaillance ANTICIPÉS (backtest prospectif, 2026-05-20)

Backtest prospectif : non pas « qu'est-ce qui est cassé » (rien, cf. annexe 1)
mais « qu'est-ce qui POURRAIT casser, sous quelle condition ». Chaque mode a un
**déclencheur mesuré** sur les données réelles. Aucun changement runtime appliqué
(prudence J-4) — anticipation + mitigation datée.

| # | Mode de défaillance | Déclencheur (mesuré) | Risque | Impact | Mitigation / quand |
|---|---|---|---|---|---|
| **R2/R6** 🔴 | Recalibration pousse TOUS les scores au plancher 0,30 | ÷1,2/jour (orderbook 0,50→0,35 en 2j) ; lookback 30j inclut le contaminé pré-fix jusqu'à ~2026-06-16 | **Moyen-élevé, near-term** | Dans 1-2 j, l'evidence affichera toutes les sources ~30-35 % → la trader croit Tik « tout pourri » (artefact, cosmétique post-ADR-018) | Geler/reset la recalibration post-J+10 quand données propres ; OU afficher le score statique. **Surtout : prévenir la trader** |
| **R3** 🟡 | Veracity gonflée par peu de sources | 35 signaux N=2 → veracity 0,95 ; 1 signal N=1 → 0,85 | Moyen | Si GDELT/CC tombent → signaux N≤2 « 95 % » trivialement concordants passent le filtre ≥0,85 | Pénaliser la veracity quand N petit (post-trading, vrai amélioration) |
| **R5** 🟡 | Désynchro du seuil 0,85 quand Reddit revient | Seuil dans **5 fichiers** (glossary, veracity-gauge, index, script, CLAUDE.md) ; Reddit toujours 403 | Moyen | Retour Reddit → doit redevenir 0,90 → oubli d'un fichier = UI incohérente | Constante unique source de vérité (refacto) ; sinon checklist des 5 fichiers |
| **R1** 🟢 | Cap dashboard « Activité 24h » à 500 | max 24h actuel = 356 (marge 29 %) | Faible | Si volume > 500/24h (marché volatil, +entity/horizon) → compteur figé | Monter `limit` ou paginer si volume croît |
| **R4** 🟢 | Dates macro 2027 = estimations | 16 events 2027 hardcodés | Faible (futur) | Quand les BC publient les vrais calendriers 2027 (mi-2026) → fausses alertes ±4h | MAJ `macro_calendar_data.py` (backlog #7 A.4) |
| **R8** 🟢 | Régression Bug 9 (asyncpg tz) | workaround strip tzinfo dans publisher seul | Faible | Nouvelle colonne datetime aware insérée sans strip → DataError, perte signaux | Gardé par test pytest (Paquet 31) ; vigilance sur tout nouvel INSERT |
| **R9** 🟢 | Ollama down complet (vs timeout occasionnel) | warnings ReadTimeout `consecutive_failures=1` | Faible | Si Ollama tombe → 3 échecs → circuit breaker → 100 % hypothèses template | Géré (fallback ADR-012) ; dégrade seulement le contexte narratif |

**Le plus urgent à anticiper (R2/R6)** : la recalibration tourne sur des données
contaminées et pousse les scores de crédibilité affichés vers 0,30. **Dans
quelques jours, le détail de chaque signal montrera toutes ses sources à ~30 %.**
C'est un **artefact cosmétique** (post-ADR-018 le score n'alimente que
l'affichage, pas la direction/veracity) — mais visuellement alarmant pour une
débutante. À expliquer à la trader AVANT qu'elle le voie, et à geler/reset
post-J+10 quand la fenêtre de 30j ne contiendra plus que des données propres.

**Consensus anticipation** : aucun mode ne casse le pipeline ni ne corrompt les
signaux. Le seul à impact visible near-term (R2/R6) est **cosmétique**. Les
autres sont latents/futurs, tracés avec déclencheur et mitigation. Tik est
robuste ; les risques sont connus, datés et bornés.
