# Tik

**Tik** — Moteur OSINT modulaire pour décision augmentée.

Plateforme d'agrégation multi-sources, scoring de crédibilité, détection de fake news, et production de signaux pondérés par horizon, conçue pour alimenter des bots de trading (Zeta, Totem) et s'étendre à d'autres domaines (betting, politique, météo-finance).

---

## Architecture

```
Tik/
├── core/               # Service FastAPI central (source de vérité)
├── sdk/                # Package Python pip-installable (à venir, paquet 2)
├── dashboard/          # Dashboard Expo mobile (à venir, paquet 3)
└── docs/               # ADR (Architecture Decision Records) et spec
```

**Principe 3 couches** :

1. **Core engine** — agrégation OSINT, scoring véracité, détection fake news, historisation. Un seul déploiement central.
2. **SDK** — package Python importé par chaque bot (Zeta, Totem…), cache local, fallback offline, hooks évènementiels.
3. **Config YAML** — par bot et par stratégie, hot-reloadable sans redéploiement.

---

## État actuel

| Paquet | Statut |
|---|---|
| Paquet 1 — Core MVP | ✅ Livré |
| Paquet 2 — SDK Python | ⏳ À venir |
| Paquet 3 — Dashboard Expo | ⏳ À venir |

---

## Démarrage rapide (Core)

```bash
cd core
cp .env.example .env          # éditer les secrets
docker compose up -d
# API disponible sur http://localhost:8200
# Swagger sur http://localhost:8200/docs
```

Voir `core/README.md` pour les détails.

---

## Documentation

- [Spec complète v1.2](docs/SPEC_v1.2.md) — *(à ajouter depuis les documents existants)*
- [ADR-001 — Authentification pluggable](docs/adr/001-auth-pluggable.md)
- [ADR-002 — Monorepo](docs/adr/002-monorepo.md)
- [ADR-003 — Intégration Zeta sans bypass V01-V15](docs/adr/003-zeta-integration.md)
- [ADR-004 — Architecture multi-overlay pour la cross-validation](docs/adr/004-multi-overlay-architecture.md)
- [Comprendre Tik (guide pédagogique)](docs/comprendre_tik.md)

---

## Licence

Propriétaire — All Rights Reserved. Voir [LICENSE](LICENSE).

---

© 2026 — Tik
