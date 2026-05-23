#!/usr/bin/env bash
# =============================================================================
#  RAPPORT GO / NO-GO TIK — fiabilité directionnelle post-fix Bug N=2
# =============================================================================
#
#  À LANCER LE 2026-05-27 (J+10 post-fix), quand ~399 signaux swing BTC sont
#  mûrs à 5 jours (l'horizon de design du swing). Avant cette date, la section
#  principale [1] aura trop peu de signaux mûrs (warning N faible) — c'est normal.
#
#  USAGE (depuis /opt/tik sur le VPS) :
#      bash go_no_go_report.sh
#  Pour garder une trace :
#      bash go_no_go_report.sh > rapport_go_no_go_$(date -u +%Y%m%d).txt
#
#  LECTURE — la SEULE question qui compte :
#  « Tik bat-il Always SHORT (= la tendance) sur le GAIN, significativement ? »
#  Regarde la ligne « ⚠/✅ Tik (N')AJOUTE (PAS) d'alpha » de la section [1].
#    ✅ Tik AJOUTE de l'alpha au-dessus de la MEILLEURE baseline  → edge possible → GO
#    ⚠  Tik N'AJOUTE PAS d'alpha (perd/égalité vs la meilleure)   → pas d'edge → NO-GO directionnel
#  Random est trivial à battre en marché tendanciel : on l'IGNORE.
#
#  Lecture seule. N'écrit rien, ne touche ni au pipeline ni aux signaux.
# =============================================================================

M="docker exec tik-core python -m tik_core.scripts.measure_post_fix_hit_rates"
D="docker exec tik-core python -m tik_core.scripts.backtest_dual_lens"

echo "######################################################################"
echo "#  RAPPORT GO / NO-GO TIK — $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "#  Seuil swing = 0.5% (horizon de design Paquet 17). Compare vs Always SHORT."
echo "######################################################################"

echo
echo ">>> [1/5] *** MESURE PRINCIPALE *** — swing BTC à 5j (horizon de design)"
echo "    C'est CETTE section qui décide le go/no-go."
$M --entity BTC --signal-horizon swing --horizon-days 5 --threshold 0.5

echo
echo ">>> [2/5] Triangulation — swing BTC à 48h"
$M --entity BTC --signal-horizon swing --horizon-hours 48 --threshold 0.5

echo
echo ">>> [3/5] Triangulation — swing BTC à 24h"
$M --entity BTC --signal-horizon swing --horizon-hours 24 --threshold 0.5

echo
echo ">>> [4/5] Scrutin paranoïaque — dual-lens swing BTC à 5j (Bonferroni + gain)"
echo "    Confirme que tout edge apparent en [1] survit au multiple-testing."
$D --signal-horizon swing --entity BTC --horizon-days 5 --threshold 0.5

echo
echo ">>> [5/5] Secondaire — flash BTC à 1h (horizon de design flash)"
$M --entity BTC --signal-horizon flash --horizon-hours 1 --threshold 0.3

echo
echo "######################################################################"
echo "#  VERDICT"
echo "#  GO directionnel UNIQUEMENT si, en section [1] :"
echo "#    (a) ✅ Tik AJOUTE de l'alpha au-dessus de la meilleure baseline, ET"
echo "#    (b) N >= ~30 (pas de warning échantillon faible), ET"
echo "#    (c) confirmé en [4] (survit Bonferroni + gain positif)."
echo "#  Sinon → NO-GO directionnel : sizing 1%, Tik = outil de CONTEXTE."
echo "#"
echo "#  ATTENTION RÉGIME : si BTC n'a fait que baisser sur la fenêtre, un edge"
echo "#  apparent peut n'être que 'short dans un downtrend'. Un vrai edge se"
echo "#  confirme sur un régime MIXTE (hausse + baisse). À garder en tête."
echo "######################################################################"
