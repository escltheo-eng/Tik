# Tik Dashboard

Application Expo (React Native + web) pour visualiser en temps réel les signaux OSINT produits par le core Tik. Couche 3 de l'architecture (cf. `CLAUDE.md` racine du repo).

**Statut** : Paquet 3 — Session 1 livrée (bootstrap + écran d'accueil).

## Garde-fous

- **Lecture seule** : conformément à l'ADR-003, ce dashboard ne passe jamais d'ordre et n'altère pas les bots Zeta/Totem. Il consomme uniquement les endpoints HTTP REST et WebSocket exposés par le core.
- **Indépendant du SDK Python** : le dashboard tape directement le core via `fetch` et `WebSocket` natifs. Mêmes endpoints, même auth (Bearer token sur HTTP, query param `?api_key=...` sur WebSocket).

## Stack technique

| Couche | Choix |
|---|---|
| Framework | Expo SDK 54 |
| Langage | TypeScript 5.9 |
| Routing | Expo Router 6 (file-based) |
| UI | React 19 + React Native 0.81 |
| Cibles | Web (`react-native-web`), iOS (Expo Go puis EAS Build), Android (idem) |

## Prérequis

- **Node.js 22+ ou 24+** installé sur le Mac (testé avec v24.15.0).
- Aucun Xcode requis pour démarrer en mode web ou Expo Go.

## Démarrer en mode web (recommandé pour le dev)

Depuis le dossier `dashboard/` :

```bash
npm install   # uniquement la première fois
npm run web
```

Ouvrir l'URL affichée dans le terminal (typiquement http://localhost:8081). Le hot-reload est actif : modifier un fichier dans `app/` rafraîchit automatiquement la page.

## Démarrer sur iPhone via Expo Go

1. Installer l'app **Expo Go** (gratuite) depuis l'App Store sur l'iPhone.
2. Mac et iPhone doivent être sur le **même Wi-Fi**.
3. Depuis le dossier `dashboard/` :
   ```bash
   npm start
   ```
4. Scanner le QR code affiché dans le terminal avec l'appareil photo de l'iPhone.

## Structure du projet

```
dashboard/
├── app/                    # Expo Router (file-based routing)
│   ├── _layout.tsx         # Root layout (Stack + ThemeProvider)
│   ├── modal.tsx           # Exemple de modal (template)
│   └── (tabs)/             # Navigation par onglets
│       ├── _layout.tsx     # Définition des onglets
│       ├── index.tsx       # Écran Home (KPIs et statut)
│       └── about.tsx       # Écran About (vision Tik, ADR, garde-fous)
├── components/             # Composants réutilisables (themed, parallax, etc.)
├── constants/              # Couleurs, fonts, theme
├── hooks/                  # Hooks React custom (useColorScheme, useThemeColor)
├── assets/                 # Images, icônes, fonts
├── app.json                # Config Expo
├── package.json
└── tsconfig.json
```

## Roadmap Paquet 3

| # | Session | Périmètre | Statut |
|---|---|---|---|
| 1 | Bootstrap & Hello World | Projet Expo, écran d'accueil, mode web fonctionnel | ✅ livrée |
| 2 | Auth + client HTTP | Login API key, SecureStore, client HTTP partagé | ⏳ à venir |
| 3 | WebSocket + Signals Feed | Stream live, écran liste signaux | ⏳ à venir |
| 4 | KPIs + Charts | Prix BTC/GOLD live, graphes Victory ou Skia | ⏳ à venir |
| 5 | Notifications push + polish | Expo Push, écrans Alerts/Bots/Config | ⏳ à venir |

## Liens utiles

- [`CLAUDE.md`](../CLAUDE.md) à la racine : contexte général du projet Tik.
- [`docs/comprendre_tik.md`](../docs/comprendre_tik.md) : guide pédagogique sans prérequis technique.
- [`docs/adr/`](../docs/adr/) : décisions architecturales (notamment ADR-003 lecture seule).
- [`sdk/README.md`](../sdk/README.md) : SDK Python (Paquet 2, version 0.5.0) — référence des modèles miroirs.
