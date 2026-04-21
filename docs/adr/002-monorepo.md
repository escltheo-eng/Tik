# ADR-002 — Monorepo Tik

- **Statut** : Accepté
- **Date** : 2026-04-20

## Contexte

Tik se compose de 3 paquets : **core** (service FastAPI central), **sdk**
(package Python pip-installable pour bots clients), **dashboard** (app Expo
mobile). Se pose la question : un seul repo (monorepo) ou trois repos séparés
(polyrepo) ?

## Décision

**Monorepo** unique `Tik/` avec sous-dossiers `core/`, `sdk/`, `dashboard/`, `docs/`.

## Justification

- **Solo dev** : un seul historique git, un seul workflow de PR, pas de
  coordination cross-repo.
- **Changements transverses fréquents** : ajouter un champ dans les schémas
  de signaux impacte core + sdk + dashboard → un seul commit au lieu de trois
  PRs synchronisées.
- **Versioning simplifié** : le tag git s'applique à l'ensemble ; pas de
  matrice de compatibilité core ↔ sdk à gérer.
- **Découverte simplifiée** : un nouvel arrivant (ou l'utilisateur lui-même
  dans 6 mois) clone un repo et a tout sous les yeux.
- **Extensibilité** : si un composant devient énorme et impose son propre
  cycle de release, on peut extraire un sous-dossier dans un repo séparé
  avec `git subtree split` — sans perdre l'historique.

## Conséquences

**Positives**
- Simplicité opérationnelle maximale pour solo dev
- Commits atomiques sur changements transverses
- Documentation centralisée dans `docs/`

**Négatives**
- CI doit filtrer par chemin pour ne pas rebuild tout à chaque commit
  (résolu avec `paths:` dans GitHub Actions)
- Accès granulaire (ex : exposer publiquement seulement le SDK) impossible
  sans découpage
- Package SDK publié séparément : nécessite de préciser le sous-dossier au
  moment de l'upload registry

## Alternatives rejetées

- **Polyrepo (3 repos)** : triple overhead sans bénéfice tant qu'on est
  seul et que les composants évoluent en synchronisation.
- **Mono-package** (core + sdk dans le même package Python) : empêche les
  clients légers d'installer uniquement le SDK (obligation de tirer asyncpg,
  alembic, FRED dependencies inutilement).

## Mise en œuvre CI

`.github/workflows/ci.yml` utilise `paths:` pour ne déclencher les jobs
`core` que sur les changements dans `core/`, et idem pour sdk/dashboard.
