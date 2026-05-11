# Checklist post-récupération Mac

**Créée le 2026-05-11 pendant la période Windows HP** (Mac en panne depuis ~2026-05-11, cf. mémoire Claude `project_platform_windows_period.md`).

**À suivre étape par étape dès que tu récupères ton Mac.** Tu peux cocher les cases mentalement ou imprimer ce fichier. Si une étape échoue, ne saute pas — résous-la avant de passer à la suivante. Le but : éviter de découvrir un bug pendant le trading manuel J+14 alors qu'on aurait pu le voir en 5 min de vérification proactive.

**Outils nécessaires côté Mac (déjà installés avant la panne)** : Docker Desktop, Ollama (avec `llama3.2:3b`), VS Code, GitHub Desktop, navigateur (Safari), terminal (zsh).

**Outils nécessaires côté iPhone** : Expo Go (déjà installé), WiFi maison joint (même réseau que Mac).

**Estimation effort total** : 60-90 min en cumulé. Tu peux faire en plusieurs sessions.

---

## Phase 1 — Démarrage Mac + sanity check (5 min)

- [ ] Allumer le Mac, attendre le boot complet
- [ ] Vérifier qu'il n'y a pas d'écran d'erreur disque / Time Machine prompt anormal
- [ ] Ouvrir Finder → vérifier que `/Users/siku/Documents/Tik/` est toujours là et accessible
- [ ] Ouvrir un terminal (Spotlight → Terminal)
- [ ] `df -h` → vérifier qu'il reste au moins 20 Go libre sur le disque (Docker en consomme beaucoup)

**Si quelque chose semble cassé sur le Mac (disque, fichiers manquants, etc.)** : NE PAS continuer la checklist. Plutôt :
1. Faire un Time Machine restore si tu en as un récent
2. Sinon : noter ce qui manque + demander à une instance Claude de t'aider à reconstruire depuis le repo GitHub (qui a tout en sécurité)

---

## Phase 2 — Récupérer les commits du Windows (5-10 min)

Pendant la période Windows, j'ai créé une branche `work-from-hp` avec plusieurs commits non-mergés à `main`. Côté Mac, ils sont **distants seulement** — il faut les rapatrier.

### Si tu utilises GitHub Desktop
- [ ] Ouvrir GitHub Desktop
- [ ] Repository → Pull (récupère les nouveautés)
- [ ] Branch → Switch to → **`work-from-hp`** (la branche du Windows)
- [ ] Vérifier que tu vois les 3 derniers commits :
  - `915e7b2` docs(adr): ADR-019 — politique no-op manuel SOURCE_SCORES
  - `1381fbd` docs(claude): Paquet 20 — Phase C Session 2 Watchlist livré
  - `21418c7` feat(dashboard): Phase C Session 2 J+10 — Watchlist auto-resolve…
- [ ] **Décision** : merger `work-from-hp` dans `main` ou continuer à travailler sur `work-from-hp` ?
  - Recommandation : **merger dans `main`** une fois que tu auras validé que tout marche (cf. Phase 5 + 6). Pas avant — tant que le code n'est pas validé runtime, garder la séparation est plus prudent.

### Si tu préfères en ligne de commande
- [ ] `cd ~/Documents/Tik`
- [ ] `git fetch --all`
- [ ] `git checkout work-from-hp`
- [ ] `git log --oneline -5` → vérifier que les 3 commits ci-dessus sont bien là

---

## Phase 3 — Docker + Tik backend (10-15 min)

- [ ] Lancer Docker Desktop (icône baleine dans la barre de menus Mac → attendre qu'elle soit verte/blanche, pas orange)
- [ ] Vérifier qu'il y a assez de RAM allouée à Docker : Docker Desktop → Settings → Resources → Memory ≥ 4 GB (idéalement 6 GB)
- [ ] Dans un terminal : `cd ~/Documents/Tik/core`
- [ ] **Important** : `docker compose ps` → état actuel ?
  - **Si tous les conteneurs sont arrêtés** (état `Exited`) : passer au lancement
  - **Si certains tournent encore** (Mac a pu les laisser en l'état) : `docker compose down` d'abord pour repartir propre
- [ ] Lancer : `docker compose up -d`
- [ ] Attendre ~30 secondes que Postgres + Redis montent
- [ ] `docker compose ps` → vérifier que les **5 services** sont `Up` ou `Up (healthy)` :
  - `tik-core` (port 8200)
  - `tik-ingesters`
  - `tik-scheduler`
  - `tik-postgres` (port 5432)
  - `tik-redis` (port 6379)
- [ ] Test santé API : `curl http://localhost:8200/api/v1/health`
  - Attendu : `{"status":"ok","version":"...","env":"..."}`
  - Si erreur : `docker compose logs --tail=50 core` puis demander à Claude
- [ ] Vérifier que les 4 derniers signaux sont OK : `curl -H "Authorization: Bearer <ta_clé_api>" http://localhost:8200/api/v1/signals/latest?limit=4 | plutil -convert json -r -o - -`
  - Attendu : 4 signaux JSON avec timestamps récents
  - **Vérifier les timestamps** : ils doivent être en heure UTC (`...Z`). Si pas, c'est une régression du bug 8/9 timezone — alerter Claude immédiatement.

### Intégrité DB Postgres (important — vérifier qu'aucune donnée n'a été corrompue par la panne)

- [ ] `docker exec -it tik-postgres psql -U tik -d tik -c "SELECT COUNT(*) FROM signals;"`
  - Attendu : un nombre cohérent (devrait correspondre à ce qu'il y avait avant la panne + 0 nouveau si Tik n'a pas tourné entre temps)
- [ ] `docker exec -it tik-postgres psql -U tik -d tik -c "SELECT COUNT(*) FROM headlines;"`
  - Attendu : nombre raisonnable de titres en historique
- [ ] `docker exec -it tik-postgres psql -U tik -d tik -c "SELECT COUNT(*) FROM source_credibility_history;"`
  - Attendu : ≥ 1 par cycle daily 03h UTC × jours écoulés depuis Paquet 5 (livré 2026-05-03). Si 0 : Paquet 5 n'a pas tourné comme prévu → audit nécessaire.

---

## Phase 4 — Ollama (5 min)

L'utilisatrice avait installé Ollama natif sur le Mac (cf. Paquet 1.x + ADR-006). Vérifier qu'il tourne toujours et que `llama3.2:3b` est encore là.

- [ ] Icône lama dans la barre de menus Mac visible ? Si non : `open -a Ollama` dans le terminal
- [ ] Tester santé : `curl http://localhost:11434/api/tags`
  - Attendu : JSON avec une clé `models` qui contient un objet avec `"name":"llama3.2:3b"`
- [ ] **Si `llama3.2:3b` manque** (suite à panne disque par exemple) : `ollama pull llama3.2:3b` (~2 GB, 5-10 min de download)
- [ ] Vérifier que les conteneurs Docker peuvent atteindre Ollama :
  - `docker exec -it tik-scheduler curl -s http://host.docker.internal:11434/api/tags | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('models',[])[0].get('name','MISSING'))"`
  - Attendu : `llama3.2:3b` affiché
  - Si erreur : Docker n'arrive pas à atteindre Ollama via `host.docker.internal`. Cause probable : Ollama n'écoute pas sur 0.0.0.0. Solution : variable d'env `OLLAMA_HOST=0.0.0.0:11434` au démarrage Ollama (cf. ADR-006).

---

## Phase 5 — Validation Phase C Session 2 dashboard (Paquet 20, livré 2026-05-11) (15-20 min)

Le code Phase C Session 2 a été poussé depuis Windows mais **n'a PAS été validé runtime** (Node.js pas installé sur Windows, Tik backend pas opérationnel). Tu vas le valider maintenant.

### Setup dashboard côté Mac

- [ ] Terminal : `cd ~/Documents/Tik/dashboard`
- [ ] Vérifier que `package.json` est en version `0.5.8` (bump fait pendant période Windows)
- [ ] `npm install` (~2-5 min, le package.json a changé donc des deps peuvent être à jour)
- [ ] **Validation TypeScript** : `npx tsc --noEmit`
  - Attendu : exit 0 sans erreur. Si erreurs → alerter Claude immédiatement, c'est probablement un import ou un type cassé.
- [ ] **Validation ESLint** : `npx expo lint`
  - Attendu : exit 0 (ou warnings non-bloquants seulement)
- [ ] Lancer le dev server : `npx expo start`
- [ ] QR code apparait dans le terminal

### Validation iPhone Expo Go

- [ ] iPhone connecté au WiFi maison (même réseau que le Mac)
- [ ] Ouvrir l'app Caméra native iOS → scanner le QR code → ouvre dans Expo Go
- [ ] Login : Base URL `http://192.168.1.X:8200` (ton IP locale Mac, vérifier via `ifconfig | grep "inet "` côté Mac) + ta clé API
- [ ] Onglet Signals : flux WS « Live » apparaît
- [ ] Onglet Watchlist : carte vide (normal si aucun signal suivi avant la panne)
- [ ] Aller sur un signal détail (depuis Signals), taper sur ★ Suivre
- [ ] Revenir sur Watchlist : le signal apparaît avec outcome `pending`
- [ ] **Tester l'auto-résolution** : attendre 5 min (interval du hook `useAutoResolveWatchlist`), normalement le signal reste pending si trop récent (pas encore atteint son TTL). Vérifier dans les logs Mac Expo Go que les requêtes vers `/metrics/signal_track_record/...` partent bien.
- [ ] **Tester le bouton ✎** : doit être visible UNIQUEMENT sur entries non-pending. Pour le forcer en non-pending temporairement : passe par la console JS ou attends un vrai retournement track record.
- [ ] **Tester le modal override** : (quand ✎ visible) tap → modal s'ouvre, 4 boutons outcome, zone note, bouton Valider envoie un POST `/feedback` → vérifier en DB : `docker exec -it tik-postgres psql -U tik -d tik -c "SELECT * FROM feedbacks ORDER BY received_at DESC LIMIT 3;"` — la nouvelle entrée doit avoir `exit_reason="auto_market_check"` ou `"user_override"` ou ta note libre.
- [ ] **Tester la carte HitRatePersoCard** : apparaît automatiquement quand au moins 1 signal a outcome ≠ pending.

### Issues possibles à valider

- [ ] **Pattern stopPropagation Pressable imbriqué** : taper sur ✎ ne doit PAS ouvrir le détail du signal (sinon ça veut dire que le bubble passe). Si bug → remplacer par `TouchableWithoutFeedback` ou refactor structurel.
- [ ] Empty state Watchlist toujours clair (texte « Aucun signal suivi »).
- [ ] Stats line « N suivis · N en attente · N résolus » affiche bien les bons compteurs.

---

## Phase 6 — Monitoring ADR-019 auto-cal source credibility (10 min)

ADR-019 du 2026-05-11 a acté un « no-op manuel + surveillance auto-cal ». Vérifier que l'auto-cal a tourné pendant ton absence et que ses sorties sont cohérentes.

- [ ] Query l'historique de recalibration :
  ```sql
  docker exec -it tik-postgres psql -U tik -d tik -c "SELECT source, recalibrated_at, previous_score, new_score, hit_rate, samples, adjustment FROM source_credibility_history ORDER BY recalibrated_at DESC LIMIT 20;"
  ```
- [ ] **Vérifier** :
  - Au moins 1 entry par jour entre le dernier cycle pré-panne et aujourd'hui. Si gap : auto-cal a manqué des cycles (Tik ne tournait pas).
  - Si gap : c'est attendu et OK, le job suivant compensera (misfire_grace_time 24h, cf. commentaire `run_scheduler.py`).
  - Aucune source ne doit avoir `new_score = 0.30` (min) ou `new_score = 0.95` (max) — sinon elle est saturée et l'auto-cal ne peut plus l'ajuster. Critère C2 d'ADR-019.
  - Aucune source ne doit osciller entre `penalty` et `reward` cycles consécutifs sans tendance. Si oui : critère C1 d'ADR-019, audit manuel à prévoir.
- [ ] Si au moins 1 source paraît bloquée à un extrême ou erratique → **ne pas paniquer**, c'est exactement ce que les critères C1/C2 d'ADR-019 anticipent. Ouvrir une session Claude pour analyse + éventuel ADR-020.

---

## Phase 7 — Décision trading manuel J+14 (5 min)

J+14 = 2026-05-14. Selon quand le Mac est revenu, tu es :

- **Avant le 14 mai** : tu as encore de la marge. Suivre Garde-fou 2-bis (sizing 1 % capital, filtre veracity ≥ 0.90 sur swing, discipline macro ±4 h autour event HIGH FOMC/NFP/CPI). Premier trade comme prévu le 14 mai.
- **Le 14 mai** : déjà aujourd'hui. Décider si tu prends ton premier trade :
  - Tik tourne depuis < 24 h post-récup ? Reporter de quelques jours (mode shadow pour vérifier qu'il n'y a pas de régression silencieuse).
  - Tik tourne stable depuis ≥ 24 h ? Tu peux y aller selon Garde-fou 2-bis.
- **Après le 14 mai** : J+14 a glissé. Pas grave — le plan était calibré pour la date initiale, pas un dogme. Démarrer dès que Tik est stable depuis ≥ 24 h post-récupération. Garde-fou 2-bis inchangé.

### Rappel Garde-fou 2-bis (CLAUDE.md section 5)

- **Sizing : 1 % du capital par trade** au démarrage, pas 5 % (le 5 % est calibré pour Zeta auto, pas trading manuel).
- **Filtre veracity ≥ 0.90 sur swing** (insight Phase A.2-bis : 67 % hit sur veracity 0.95+ vs 24 % global).
- **Discipline calendrier macro** : pas de swing dans ±4 h autour d'event HIGH (FOMC, NFP, CPI). Si trade forcé autour event : sizing ÷ 2 (= 0.5 %).
- **Période d'observation** : 2 semaines minimum à 1 %, montée progressive **uniquement** après période profitable mesurable.

---

## Phase 8 — Cleanup état Claude pour les prochaines sessions (5 min)

Maintenant que tu as récupéré le Mac, certaines mémoires Claude ne sont plus pertinentes.

- [ ] Quand tu commences ta prochaine session Claude (`claude code` sur le Mac), dis simplement : **« j'ai récupéré mon Mac »**.
- [ ] L'instance Claude saura alors :
  - Désactiver l'auto commit + push (la règle ne s'applique plus, retour au mode normal « commit + push seulement sur demande explicite »).
  - Mettre à jour CLAUDE.md section 11 pour retirer la mention « période Windows HP ».
  - Archiver les mémoires `feedback_auto_commit_push_windows.md` et `project_platform_windows_period.md` (Claude saura les retirer du MEMORY.md index).

### Action manuelle optionnelle

- [ ] Merger `work-from-hp` dans `main` une fois que Phase 5 est validée :
  - GitHub Desktop : Branch → Merge into current branch → choisir `work-from-hp`
  - Ou ligne de commande : `git checkout main && git merge work-from-hp && git push`
- [ ] Supprimer la branche `work-from-hp` une fois mergée :
  - GitHub Desktop : Branch → Delete (cocher « delete remote branch »)
  - Ou : `git branch -d work-from-hp && git push origin --delete work-from-hp`

---

## Si quelque chose tourne mal

À chaque étape qui échoue : **arrête, prends une photo / screenshot de l'erreur, ouvre une session Claude avec le contexte**. Ne pas improviser.

**Risques connus à anticiper** :

- **Bug 8/9 timezone** (cf. CLAUDE.md section 9) : si tu vois des âges « il y a 2 h » alors que tu sais que c'est il y a 5 min, c'est une régression du fix Paquet 7 (ADR-013). Workaround dans `core/src/tik_core/scoring/publisher.py` doit être en place. Si pas, restaurer le code depuis le repo.
- **Premier cycle scheduler post-restart** : peut prendre jusqu'à 30 min selon le job (flash = 5 min, swing BTC = 15 min, swing GOLD = 30 min). Ne pas s'inquiéter si pas de signal dans les 5 premières minutes.
- **WebSocket auth refused** (bug 7 section 9) : si dashboard reste sur « Reconnexion… », le bug `_session_maker` est revenu. Restaurer le code de `core/src/tik_core/api/ws.py`.

**Liste des sources de vérité** (par ordre de priorité de consultation) :

1. **CLAUDE.md** — état projet à jour
2. **ADRs récents** : ADR-018 (Tik OSINT pur), ADR-019 (no-op SOURCE_SCORES), ADR-017 (calendrier macro), ADR-013 (timezone), ADR-011 (anti fake-news + auto-cal source credibility), ADR-012 (LLM hypothesis)
3. **Mémoires Claude** : `feedback_auto_commit_push_windows.md`, `project_platform_windows_period.md` (à archiver après récup Mac)
4. **`docs/comprendre_tik.md`** — pédagogie FR si tu veux te rafraîchir sur un concept

---

**Dernière mise à jour : 2026-05-11** *(par Claude pendant la période Windows HP)*

**Verdict global** : si toutes les phases passent ✓, Tik est sain et tu peux reprendre tes activités normales (trading manuel J+14 + plan stratégique fiabilité signaux). Si une phase échoue : pause + Claude.
