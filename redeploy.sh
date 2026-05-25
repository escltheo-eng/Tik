#!/usr/bin/env bash
# =============================================================================
#  REDEPLOY TIK — active en runtime le code committé (scheduler/ingesters/redis)
# =============================================================================
#
#  POURQUOI CE SCRIPT
#  Le scheduler et les ingesters tournent SANS `uvicorn --reload`. Quand une
#  session modifie leur code (bind-mount ./src), le fichier change sur le disque
#  mais le PROCESS en cours garde l'ancien code en mémoire jusqu'à un restart.
#  Résultat constaté le 2026-05-25 (Paquet 37) : du durcissement sécurité
#  committé le 24/05 (H2 anti-perte titres, H4 caps Polymarket, B1 SIGTERM,
#  B4 publisher, M2 Redis maxmemory) n'était PAS actif en runtime.
#  Ce script recrée proprement les conteneurs concernés pour aligner
#  runtime == code committé == docker-compose. core est exclu (il a --reload).
#
#  SÛRETÉ
#  - BGSAVE Redis AVANT recreate → perte de données quasi-nulle (volume préservé,
#    les clés Redis sont de toute façon des caches/last_price/historique shadow,
#    reconstruits en secondes-minutes).
#  - À lancer HORS d'une fenêtre macro chaude (prochain event HIGH visible via
#    l'onglet Calendrier macro du dashboard). Bref gap de production de signaux
#    (quelques minutes, toléré par la bannière de fraîcheur M4 à 60 min).
#  - NE touche PAS au pipeline de scoring (engines inchangés depuis le 2026-05-20).
#
#  USAGE (depuis le VPS) :
#      bash /opt/tik/redeploy.sh
#  Pour ne recréer qu'une partie :
#      bash /opt/tik/redeploy.sh scheduler ingesters
# =============================================================================
set -euo pipefail

COMPOSE="docker compose --project-directory /opt/tik/core -f /opt/tik/core/docker-compose.yml"
SERVICES="${*:-scheduler ingesters redis}"

echo "######################################################################"
echo "#  REDEPLOY TIK — $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "#  Services ciblés : $SERVICES"
echo "######################################################################"

# --- Baseline avant ---
echo
echo ">>> Baseline AVANT"
BEFORE_LAST=$(docker exec tik-postgres psql -U tik -d tik -t -A -c \
  "SELECT max(timestamp) FROM signals;" 2>/dev/null || echo "?")
echo "    Dernier signal : $BEFORE_LAST"
echo "    Redis DBSIZE   : $(docker exec tik-redis redis-cli DBSIZE 2>/dev/null || echo '?')"

# --- BGSAVE Redis si on recrée redis ---
if [[ " $SERVICES " == *" redis "* ]]; then
  echo
  echo ">>> BGSAVE Redis (persiste les données avant recreate)"
  docker exec tik-redis redis-cli BGSAVE
  sleep 3
  echo "    LASTSAVE : $(docker exec tik-redis redis-cli LASTSAVE)"
fi

# --- Recreate ---
echo
echo ">>> Recreate : $SERVICES"
# shellcheck disable=SC2086
$COMPOSE up -d --force-recreate $SERVICES

echo
echo ">>> Attente stabilisation (25 s)..."
sleep 25

# --- Vérifications APRÈS ---
echo
echo ">>> Vérifications APRÈS"
echo "--- conteneurs ---"
$COMPOSE ps --format 'table {{.Name}}\t{{.Status}}'

echo
echo "--- M2 : Redis maxmemory (attendu 1gb / allkeys-lru) ---"
echo "    maxmemory        = $(docker exec tik-redis redis-cli CONFIG GET maxmemory | tail -1)"
echo "    maxmemory-policy = $(docker exec tik-redis redis-cli CONFIG GET maxmemory-policy | tail -1)"
echo "    DBSIZE (survie données) = $(docker exec tik-redis redis-cli DBSIZE)"

echo
echo "--- API core répond ? ---"
curl -s -o /dev/null -w "    /health HTTP %{http_code}\n" http://localhost:8200/api/v1/health || true

echo
echo "--- Erreurs récentes ingesters/scheduler (60 dernières s) ---"
docker logs tik-ingesters --since 60s 2>&1 | grep -iE "error|traceback|exception" | tail -5 || echo "    (aucune)"
docker logs tik-scheduler  --since 60s 2>&1 | grep -iE "error|traceback|exception" | tail -5 || echo "    (aucune)"

echo
echo "--- Reprise production de signaux ? (attendre 1 cycle si vide) ---"
AFTER_LAST=$(docker exec tik-postgres psql -U tik -d tik -t -A -c \
  "SELECT max(timestamp) FROM signals;" 2>/dev/null || echo "?")
echo "    Dernier signal AVANT : $BEFORE_LAST"
echo "    Dernier signal APRÈS : $AFTER_LAST"
echo "    (le scheduler fait un premier run au démarrage ; sinon attendre le"
echo "     prochain cycle flash ~5 min / swing ~15-30 min, puis re-vérifier)"

echo
echo "######################################################################"
echo "#  Vérifie : tous 'healthy', maxmemory=1073741824, /health 200,"
echo "#  aucune erreur, et un nouveau signal apparaît au prochain cycle."
echo "#  En cas de souci : '$COMPOSE logs <service> --tail 50'"
echo "######################################################################"
