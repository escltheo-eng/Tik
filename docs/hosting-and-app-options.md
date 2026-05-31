# Hébergement Tik + distribution de l'appli — options & décision

> **Statut : DISCUSSION du 2026-05-31, DÉCISION EN ATTENTE.**
> L'utilisatrice (+ son associé) réfléchit. Ce document EST l'exposé complet
> déjà fait — une future instance Claude **ne doit pas le re-expliquer de zéro**,
> juste reprendre là où on en est et aider à trancher / répondre aux nouvelles
> questions. Public : utilisatrice **non-technique** → vocabulaire accessible.

## Le concept central à NE PAS confondre : appli ≠ connexion

Métaphore de la **radio** :
- **Tik (le cerveau : API + moteurs + base de données)** = la **station qui émet**.
  Elle tourne sur un **serveur** (le Mac de l'utilisatrice **ou** un VPS).
- **L'appli iPhone** (Expo Go ou vraie appli) = juste le **poste récepteur / l'écran**.
  Elle **ne contient pas les données** ; elle va les chercher sur la station via le réseau.

**Conséquences (sources de confusion fréquentes) :**
- « Faire une vraie appli » ne donne **PAS** l'accès « dehors ». L'accès dehors dépend
  **uniquement** d'où est la station (serveur) et si l'iPhone peut la capter de l'extérieur.
- Une station **éteinte n'émet pas** → « Tik tout le temps (24/7) » exige un **serveur
  toujours allumé**. Un Mac qu'on éteint/met en veille **ne peut pas** être 24/7.
  Aucune appli (gratuite ou payante) ne change cette règle physique.

## Le rôle de Tailscale BASCULE selon l'hébergement

Tailscale = réseau privé chiffré entre tes appareils (couloir privé par-dessus internet).

| Hébergement | Rôle de Tailscale |
|---|---|
| **VPS (IP publique)** | **Optionnel** — sécurité seulement (sortir l'API de l'internet public). L'IP publique donne déjà l'accès partout. |
| **Mac local (pas d'IP publique)** | **Nécessaire** pour atteindre Tik depuis l'extérieur (toi en 4G **et** l'associé). Pas un bonus sécurité : la *connexion* elle-même. |

- **Coût Tailscale : GRATUIT** à cette échelle (plan « Personal » non commercial,
  ~3 utilisateurs / 100 appareils → toi + associé = OK).
- **Pourquoi ça buggait avant (époque Mac + Expo Go)** : ce n'était pas vraiment
  Tailscale, mais **Expo Go** qui devait charger un **serveur de développement (Metro)**
  lourd par-dessus la 4G → gels au login, assets qui échouent. **Une vraie appli n'a
  plus besoin de Metro** (elle ne fait qu'une petite connexion légère à l'API) → Tailscale
  a de **vraies chances de marcher** là où Expo Go échouait. **À re-tester proprement.**

## Expo Go vs vraie appli (EAS Build)

| Critère | Expo Go (actuel) | Vraie appli (EAS Build) |
|---|---|---|
| Icône sur l'écran | ❌ (ouvrir Expo Go puis choisir le projet) | ✅ icône « Tik » |
| Serveur de dev (Metro) requis | ✅ oui (fragile en 4G) | ❌ non (build prod : interface embarquée) |
| Démarrage | lent | rapide (~2-3 s) |
| Stabilité 4G | 🔴 mauvaise (mesuré Paquet 16) | ✅ fiable |
| MAJ du code | live (dev) | **OTA via EAS Update** (sans réinstaller) |
| Nature | **outil de DÉV** | **produit fini** |

**Verdict long terme : la vraie appli** (EAS Build, build de production + EAS Update OTA).
Expo Go est un outil de dev, pas un produit. EAS Build compile **dans le cloud** (pas besoin
que le Mac compile ; ~30 builds/mois gratuits ; 1er build ~10-15 min). Cf. **plan Paquet 16**
dans CLAUDE.md pour les étapes concrètes (~1-2 h).

## Le coût Apple — ce n'est PAS une « licence commerciale »

Les **99 €/an (Apple Developer Program)** ne dépendent pas de « commercial vs personnel ».
C'est juste le moyen Apple de **signer et distribuer** une appli iPhone.

| | Apple ID gratuit | Apple Developer 99 €/an |
|---|---|---|
| Installer Tik sur **ton** iPhone | ✅ | ✅ |
| Durée de signature | ❌ **expire tous les 7 jours** (réinstall hebdo) | ✅ pas d'expiration |
| **Partager avec l'associé** | ❌ très galère (pas prévu pour une 2ᵉ personne à distance) | ✅ **TestFlight** (invitation par email) |
| Publier sur l'App Store public | non | possible **mais pas obligatoire** (on reste privé via TestFlight) |

→ On **n'a pas besoin de publier sur l'App Store** (ça, ce serait public/commercial).
On reste **privé** : invitation toi + associé via **TestFlight**.

## L'associé

- **Avoir l'appli** : oui, via **TestFlight** (= Apple Developer 99 €/an). L'Apple ID gratuit
  est impraticable pour une 2ᵉ personne à distance.
- **Atteindre la station** : son appli doit joindre le serveur Tik :
  - Tik **local Mac** → il faut **l'ajouter au Tailscale** (gratuit).
  - Tik **VPS** → tu lui donnes une **clé API** (accès via l'IP publique).

## Ce qui est gratuit vs ce qui coûte

| Objectif | Gratuit possible ? |
|---|---|
| Tik en local sur le Mac | ✅ gratuit |
| Tailscale (toi + associé) | ✅ gratuit (plan perso) |
| Vraie appli sur **ton** iPhone (Apple ID gratuit) | ✅ gratuit **mais réinstall tous les 7 jours** |
| Tik **dehors** quand le Mac est allumé | ✅ gratuit (Tailscale + appli) |
| Tik **24/7** | ❌ **non sans VPS** (~5 €/mois) |
| L'associé a l'appli **facilement** | ❌ pas en gratuit → **TestFlight = 99 €/an** |

## Conclusion honnête

L'idéal espéré — **gratuit + dehors + tout le temps + sans VPS + partagé à l'associé** —
**n'est pas atteignable** (règle « une station éteinte n'émet pas »). Deux scénarios cohérents :

- **Scénario A — tout gratuit, mais limité** : Tik local sur Mac + Tailscale + appli Apple ID
  gratuit. → Marche **pour toi**, **dehors quand ton Mac est allumé**, **PAS 24/7**, associé **compliqué**.
- **Scénario B — confort « pro » à deux** : petit VPS (~5 €/mois, 24/7) + vraie appli +
  Apple Developer 99 €/an + TestFlight pour l'associé. → Tik **tout le temps, partout, pour
  vous deux**, sans bidouille. Tailscale facultatif (sécurité).

**Recommandation** : pour **deux personnes qui dépendent des signaux en continu**, le **B**
(coût total ≈ 5 €/mois + 99 €/an, modeste pour un outil quotidien partagé). Le **A** convient
si l'usage est surtout **toi, à la maison, l'associé seulement occasionnellement quand le Mac tourne**.

## Pour décider (questions à poser à l'utilisatrice)

1. L'associé a-t-il besoin des signaux **quand tu n'es pas devant ton Mac** (nuit, weekend, déplacement) ?
2. Toi-même, tu veux Tik **en déplacement régulièrement**, ou surtout à la maison ?
3. Tik a besoin de **tourner en continu** pour collecter/calibrer/historiser — un Mac éteint la nuit interrompt ça : acceptable ou pas ?

→ Si « oui » à 1 ou 3 : **B (VPS)**. Si « surtout moi, à la maison » : **A** suffit.

## Références
- **Paquet 16** (CLAUDE.md) : plan EAS Build dev détaillé (étapes, coûts, limites).
- **Paquet 15** : audit sécurité Tailscale (origine de la réflexion sécurité).
- Mémoire `tik-server-hetzner` : séquence sûre pour fermer 8200 via Tailscale (si on garde le VPS).
- Mémoire `hosting-app-distribution-decision` : résumé de CETTE discussion (recall future instance).
