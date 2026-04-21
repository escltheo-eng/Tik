# ADR-003 — Intégration Zeta sans bypass du guard V01-V15

- **Statut** : Accepté
- **Date** : 2026-04-20

## Contexte

Zeta dispose d'un **guard pipeline V01-V15** dans `cranial_bot/micro_live_guard.py`
qui protège le capital via 15 checks bloquants (spread, marge, distance
liquidation, perte jour/semaine, positions max, trades/jour, heures UTC,
kill switch, taille cappée, trades/semaine, ESMA compliance, leverage 1:1000,
limite par symbole, cooldown). Un seul échec = trade rejeté.

Ce guard est le résultat d'un investissement substantiel : audits d'avril 2026
(40+ fixes, 17 bugs, recalibrations SL/TP, soft SL). C'est la **source de
vérité de la protection capital** chez Zeta.

La question : Tik envoie des signaux. Faut-il permettre à Tik de les
« pousser » directement à l'exécution MT5, ou doivent-ils systématiquement
passer par le guard ?

## Décision

**Jamais de bypass.** Tout signal Tik consommé par Zeta traverse **intégralement**
le pipeline V01-V15 et le `risk_engine.py` existants. Tik n'est qu'une
**source d'edge additionnelle** pour `turbo_v2.py`, pas un canal d'exécution
privilégié.

## Règles d'intégration

1. **Tik ne crée jamais d'ordre MT5 directement.** Le SDK client n'expose
   aucune méthode `place_order`.
2. **Un signal Tik modifie la `confidence` d'un signal interne Zeta**, ou
   propose un signal candidat, mais `turbo_v2.py` garde le dernier mot.
3. **Le guard V01-V15 s'applique intégralement** même si un signal Tik
   arrive avec `confidence=1.0, veracity=1.0`.
4. **Le `risk_engine.py` calcule la taille**, pas Tik. Les champs
   `suggested_entry/stop/target` que Tik expose sont **indicatifs**,
   consultables pour logs, pas appliqués automatiquement.
5. **Un nouveau check V16 optionnel** peut être ajouté dans le guard :
   « veracity globale Tik > seuil ». Activable par config ; quand actif
   ET véracité en collapse, bloque les nouveaux trades. Il s'**ajoute**
   aux 15 existants, il ne les **remplace** pas.
6. **Le `kill_switch_service.py` existant est la seule façon pour Tik
   de freezer Zeta**. Pas de API parallèle de gel.
7. **Le feedback PnL Zeta → Tik** (`POST /feedback`) est asynchrone et
   ne bloque jamais les trades. Si Tik est down, Zeta continue normalement.

## Conséquences

**Positives**
- La protection capital de Zeta reste identique, même si Tik a un bug ou
  se fait compromettre.
- Le framework « paranoïa contrôlée » de Zeta (hypothèses + 2 contre-scénarios
  + preuves min) est respecté : Tik fournit justement ces contre-scénarios
  dans chaque signal.
- Audit trail clair : tous les trades passent par les mêmes chemins.
- Si Tik est désactivé (SDK indisponible, config `tik_integration_enabled: false`),
  Zeta fonctionne exactement comme avant.

**Négatives**
- Les signaux Tik haute confiance peuvent être filtrés par le guard (ex :
  V06 positions max, V07 trades/jour). C'est une feature, pas un bug.
- Légère latence supplémentaire (overlay Tik + guard existant) — négligeable
  en horizons swing/macro.

## Points d'intégration concrets

Fichiers Zeta modifiés pour héberger l'overlay Tik :

- `cranial_bot/turbo_v2.py` — overlay confidence avant décision
- `cranial_bot/micro_live_guard.py` — ajout V16 optionnel (flag config)
- `services/kill_switch_service.py` — handler pour alertes crash Tik
- `api/websocket_router.py` — relay scores Tik vers front Zeta existant

Aucun fichier Zeta n'est **remplacé** par Tik. Uniquement **augmenté**.

## Alternatives rejetées

- **Canal d'exécution privilégié Tik** : dangereux, contourne le guard
  durement gagné, viole la philosophie « paranoïa contrôlée ».
- **Réimplémenter le guard côté Tik** : duplication dangereuse de la logique,
  risque de désynchronisation, viole la règle « source de vérité unique »
  de `balance_service.py`.
