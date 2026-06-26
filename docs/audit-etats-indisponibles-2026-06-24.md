# Audit — états « donnée/élément inaccessible » du dashboard (2026-06-24)

Audit E2E statique (lecture de code, app non exécutée) de **tous** les états où le
dashboard Expo affiche « indisponible / vide / erreur / désactivé / bientôt », page
par page, avec la **cause** et le verdict **🔧 corrigible** vs **✋ by-design (honnête,
ne pas masquer — Axe #1)**. Réalisé via 3 sous-agents (Cockpit/Signals, Macro,
Sources/Nav). Sévérité : 🔴 trompeur/bloquant · 🟠 dégradé · 🟡 cosmétique/attendu.

## Les 5 causes racines (~90 % des cas)
1. **Connexion/clé** : défaut `localhost` (faux sur iPhone, `storage.ts:50`) ; **scope
   manquant** (une clé `read:signals` ne lit ni le carnet `read:trades` ni la veracity
   `read:veracity`) ; **pas de déconnexion auto** sur clé expirée → « tout vide » sans
   explication.
2. **Sources OSINT dégradées (connues)** : Reddit IP-banni (Bug 11) + CryptoCompare hors
   quota (Bug 15) → BTC swing 2/4 overlays → neutral / veracity 0.70 / evidence pauvre ;
   GDELT 429.
3. **Micro = SHADOW (ADR-033)** : track-record → 400, jamais auto-résolu en watchlist,
   filtre « Micro » vide si le conteneur ne POSTe pas.
4. **Ingester macro pas encore publié** → « Aucune donnée collectée ».
5. **Structurel marché** : Yahoo (or) fermé week-end/nuit + délai 15 min.

## Top priorités CORRIGIBLES
1. 🔴 Défaut `localhost` au login (`storage.ts:50`).
2. 🔴 Pas de déconnexion auto sur 401/403 (`AuthContext`).
3. 🔴 Macro : 1 appel raté = 3 cartes rouges (découpler `useMacroRegime` par sous-champ)
   + message « pas d'ingester » trompeur (Liquidité/Risque = sous-champs du même blob).
4. 🟠 Messages d'erreur = dump technique → helper `humanizeError` / composant
   `<UnavailableState>`.
5. 🟠 Scope de clé (carnet/veracity) → clé `dashboard-full` avec le bon bundle.
6. 🟠 Routes mortes `bots` / `modal` / `signal/[id]` → câbler ou supprimer.

## À NE PAS « corriger » (✋ by-design, honnêteté Axe #1)
Sources Reddit/CryptoCompare muettes (pannes réelles affichées), micro shadow
(track-record 400, jamais résolu), triggers poids-0 (ADR-018), DXY/COT désactivés
(ADR-018 P2), « 🌙 GOLD fermé » week-end, discipline « Prudence » (NO-GO).

> La liste détaillée page-par-page (≈ 80 états recensés) et la stratégie de résolution
> par famille (différents moyens + instructions + « encore plus loin ») sont dans
> l'historique de la session du 2026-06-24. Synthèse opérationnelle ci-dessus.

## Méthode récurrente retenue
Cf. CLAUDE.md §13ter « Contrat des 4 états » — à appliquer/vérifier chaque session
touchant l'UI ou les données.
