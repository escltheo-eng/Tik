# ADR-001 — Authentification pluggable (API key → OAuth2)

- **Statut** : Accepté
- **Date** : 2026-04-20

## Contexte

Tik doit authentifier les bots clients (Zeta, Totem, futurs). Le besoin actuel
est simple : quelques clients connus, scopes limités, MVP propriétaire. Une
simple clé API Bearer suffit.

Cependant, l'utilisateur a explicitement mentionné qu'il pourrait passer à
OAuth2 plus tard si les besoins évoluent (ex : clients tiers, délégation
d'accès, rotation automatique de tokens, audit granulaire, multi-tenant).

Le risque est qu'en codant les endpoints avec des appels `api_key` en dur,
un changement d'auth ultérieur exige de refactorer 40+ fichiers.

## Décision

L'authentification est **pluggable via une interface abstraite `AuthProvider`**.
Les endpoints utilisent uniquement `Depends(get_auth_context)` qui retourne
un `AuthContext` indépendant du provider. Ce contexte contient les champs
métier (`client_id`, `scopes`, `auth_method`, `extra`) que les endpoints
consomment sans connaître la méthode d'auth sous-jacente.

Aujourd'hui : `ApiKeyProvider`. Demain : `OAuth2Provider` ajouté sans toucher
les endpoints.

Le choix du provider est contrôlé par la variable d'environnement
`TIK_AUTH_PROVIDER=api_key | oauth2` (config Pydantic Settings).

## Structure

```
auth/
├── provider.py        # AuthProvider (ABC) + AuthContext (dataclass)
├── api_key.py         # ApiKeyProvider (actuel)
├── dependencies.py    # get_auth_context, require_scope
└── (futur) oauth2.py  # OAuth2Provider
```

## Conséquences

**Positives**
- Zéro code métier à toucher pour swap OAuth2 plus tard
- Tests facilités : on peut mocker `AuthProvider` directement
- `require_scope("write:feedback")` utilisable partout, indépendant du provider

**Négatives**
- Légère sur-ingénierie pour le MVP (un provider unique actuellement)
- Il faut maintenir l'interface `AuthContext` stable (champs ajoutés, jamais retirés)

## Alternatives rejetées

- **Hard-coder l'API key partout** : refactor énorme au passage OAuth2.
- **Passer directement à OAuth2** : sur-ingénierie immédiate pour les besoins actuels, ajoute des dépendances (authlib, JWKS), complique le déploiement.

## Notes d'implémentation pour le passage à OAuth2

1. Créer `auth/oauth2.py` avec `OAuth2Provider(AuthProvider)`.
2. Dans `authenticate()`, valider le JWT (signature, exp, aud, iss), récupérer
   le mapping subject → client + scopes.
3. Ajouter les issuers autorisés dans la config.
4. Changer `TIK_AUTH_PROVIDER=oauth2` dans `.env`.
5. Aucun changement dans les endpoints, services, ou tests métier.
