# Setup GitHub — pas à pas

Guide pour pousser le dossier `Tik/` sur ton repo GitHub privé et
commencer à bosser dessus depuis VS Code.

---

## 1. Créer le repo GitHub

1. Va sur https://github.com/new
2. **Repository name** : `Tik`
3. **Description** : "Moteur OSINT modulaire — signaux, véracité, anti-fake-news"
4. **Privacy** : **Private** ⚠️ (impératif, code propriétaire)
5. **Ne coche rien** (pas de README, pas de .gitignore, pas de licence — on les a déjà)
6. **Create repository**

GitHub t'affiche une URL du type :
```
git@github.com:ton-user/Tik.git
```
ou
```
https://github.com/ton-user/Tik.git
```

---

## 2. Initialiser le repo local et pousser

Dans ton terminal, dans le dossier `Tik/` que tu as reçu :

```bash
cd chemin/vers/Tik

# Init git
git init
git branch -M main

# Premier commit
git add .
git commit -m "chore: initial commit — Tik core MVP (paquet 1)"

# Lier au remote GitHub
git remote add origin git@github.com:ton-user/Tik.git
# Ou si tu utilises HTTPS :
# git remote add origin https://github.com/ton-user/Tik.git

# Pousser
git push -u origin main
```

---

## 3. Ouvrir dans VS Code

```bash
code .
```

Ou depuis VS Code : **File → Open Folder...** → sélectionne le dossier `Tik/`.

---

## 4. Extensions VS Code recommandées

- **Python** (Microsoft) — linting, debugger
- **Ruff** (Astral Software) — linter rapide
- **Docker** (Microsoft) — gestion des containers
- **GitLens** (GitKraken) — historique git enrichi
- **SQLTools + SQLTools PostgreSQL Driver** — interroger la DB en local

---

## 5. Lancer le core en local

### Prérequis
- Docker Desktop installé et démarré
- Clé API FRED gratuite → https://fred.stlouisfed.org/docs/api/api_key.html

### Setup

```bash
cd core
cp .env.example .env
# Éditer .env :
# - TIK_SECRET_KEY : générer avec `openssl rand -hex 32`
# - TIK_DB_PASSWORD : choisir un mot de passe
# - TIK_FRED_API_KEY : coller la clé FRED

# Démarrer
docker compose up -d

# Suivre les logs
docker compose logs -f core
```

### Vérifier

```bash
curl http://localhost:8200/api/v1/health
# -> {"status":"ok","version":"0.1.0","env":"development"}
```

Ouvre http://localhost:8200/docs pour le Swagger UI.

### Créer la première clé API

```bash
docker compose exec core python -m tik_core.scripts.create_api_key --client zeta
```

Sauvegarde la clé affichée — elle ne sera plus visible.

### Tester un appel authentifié

```bash
curl -H "Authorization: Bearer tik_xxxxxxxxxxxxx" \
     http://localhost:8200/api/v1/signals/latest
```

---

## 6. Workflow de dev quotidien

### Feature branch

```bash
git checkout -b feat/nom-de-la-feature
# Coder...
git add .
git commit -m "feat: description"
git push -u origin feat/nom-de-la-feature
```

Créer la PR sur GitHub.

### Tests

```bash
cd core
pip install -e ".[dev]"
pytest
```

### Lint

```bash
ruff check src/
ruff format src/
```

---

## 7. Prochaines étapes

Une fois que le core tourne en local et qu'un premier signal apparaît :

1. **Paquet 2 — SDK Python** : package `tik-sdk` à installer dans Zeta et Totem.
2. **Paquet 3 — Dashboard Expo** : app mobile.

Demande-moi ces paquets quand tu es prêt.

---

## Secrets GitHub à configurer

Dans `Settings → Secrets and variables → Actions` du repo GitHub, ajoute :

- `TIK_SECRET_KEY` — clé pour les tests CI
- `TIK_FRED_API_KEY` — pour les tests d'intégration (optionnel)

Le workflow CI (`.github/workflows/ci.yml`) les utilisera automatiquement.
