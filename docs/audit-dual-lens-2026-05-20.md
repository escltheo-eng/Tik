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
