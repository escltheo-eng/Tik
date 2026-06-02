# ADR-022 — Gel de la couche Zeta / SDK

- **Statut** : ACCEPTÉ
- **Date** : 2026-06-01
- **Décideur** : utilisatrice (solo) + Claude (audit externe)
- **Remplace/complète** : ADR-002 (monorepo), ADR-003 (intégration Zeta sans bypass), ADR-007 (architecture SDK)

## Contexte

La couche 2 de l'architecture Tik (cf. CLAUDE.md §2) est le **SDK Python
`tik-sdk`** (dossier `sdk/`, ~6 200 lignes + tests + 2 jobs CI + version 0.6.0),
conçu pour qu'un bot client (Zeta aujourd'hui, Totem demain) consomme les signaux
du core. Le câblage réel à Zeta n'a **jamais** eu lieu et reste conditionné au
mode shadow 3 mois (Garde-fou 1).

Réalité opérationnelle au 2026-06-01 :

- Le trading est **100 % manuel** (démarré le 2026-05-24). L'utilisatrice
  regarde le dashboard et trade à la main.
- Zeta n'est pas connecté à Tik et il n'y a **aucun plan daté** de le connecter.
- Le go/no-go directionnel du 2026-05-27 est **NO-GO** : Tik n'a pas d'edge de
  prédiction démontré, donc rien ne presse de l'injecter dans un bot automatisé.
- Le SDK continuait pourtant d'évoluer (ex. Paquet 22, bump 0.6.0 + alias
  `osint_conviction`) — du temps de dev investi sur une couche sans consommateur.

Un SDK maintenu pour un consommateur hypothétique est un **coût** (surface à
comprendre, à ne pas casser, CI à garder verte) sans bénéfice actuel.

## Décision

**Geler la couche Zeta/SDK.** Concrètement :

1. **On ne code plus rien dans `sdk/`** (ni feature, ni refactor, ni bump de
   version) jusqu'à ce qu'un besoin réel et daté de câbler Zeta existe.
2. **Le code est conservé intact** (pas de suppression). Le gel est **réversible
   à coût nul** : le jour où Zeta doit être câblé, on dégèle.
3. **`docs/integration_zeta.md` et les ADR-003 / ADR-007 restent valides** comme
   référence pour le dégel futur — ils ne sont pas supprimés.
4. **CI** : les jobs `sdk-lint` / `sdk-test` ne se déclenchent que sur les
   changements de `sdk/` (path filtering existant). Comme on n'y touche plus,
   ils ne tournent de fait jamais — aucune action requise, aucun coût.

### Pourquoi « geler » plutôt que « supprimer »

| Option | Pour | Contre | Verdict |
|---|---|---|---|
| **Geler** (retenu) | Réversible, zéro coût tant qu'on n'y touche pas, garde l'option Zeta ouverte | Le code reste dans le repo (poids visuel) | ✅ |
| Supprimer `sdk/` | Repo plus léger | Irréversible sans `git revert` ; perd 6 200 lignes + 2 ADR de travail ; rien ne l'exige | ❌ |
| Continuer à l'entretenir | « propre » | Coût de dev sur une couche sans consommateur, pour un edge non prouvé | ❌ |

## Conséquences

- **Pour toute instance Claude future** : ne pas modifier `sdk/` ni proposer de
  l'améliorer, sauf demande explicite de l'utilisatrice liée à un câblage Zeta
  réel. Si une session « voit » le SDK et veut le polir → **ne pas le faire**,
  c'est gelé exprès.
- **ADR-003 inchangé** : si un jour Tik est câblé à Zeta, le passage par le guard
  V01-V15 reste la règle absolue.
- **L'effort de dev se concentre sur ce qui crée de la valeur aujourd'hui** :
  contexte / discipline / alerting du dashboard et des notifications, qualité des
  tests, et la recherche d'edge dans des familles de données nouvelles (dérivés
  Binance, marchés prédictifs) — cf. CLAUDE.md §8 « Axe stratégique #1 ».

## Critère de dégel

Le SDK est dégelé si **toutes** ces conditions sont réunies :
1. Un edge directionnel mesurable est démontré (ou Tik est explicitement destiné
   à pousser du *contexte* à un bot, pas un signal), ET
2. Une décision datée de câbler Zeta (ou un autre bot) à Tik est prise, ET
3. Le mode shadow 3 mois (Garde-fou 1) est planifié.
